"""Стиль и способ отправки коммента (E4.1).

Единая точка, где выбирается, чем отправлять коммент кампании:
* **text**              — обычный текст;
* **text_with_image**   — текст + одна случайная картинка кампании;
* **sticker**           — стикер из первого пакета аккаунта.

И параметры отправки:
* **emoji policy**      — если ``use_emojis=False``, добавляем инструкцию
  «не используй эмодзи» в system prompt и на всякий случай удаляем эмодзи
  из сгенерированного текста (safety net);
* **send_as**           — если ``write_as_channel=True`` и у аккаунта есть
  разрешённый «отправитель-канал» в этом чате, отправляем от него.

Runtime-эффект: `deliver_comment` заменяет прежний вызов
`client.send_message(...)` — принимает те же параметры плюс контекст,
возвращает объект-«сообщение» с ``.id`` (как раньше).
"""

from __future__ import annotations

import asyncio
import io
import random
from typing import Any, Awaitable, Callable, Optional

import structlog

from modules.commenting.models import Campaign, CampaignMediaAsset
from worker.health import around_telethon_call
from worker.llm import StyleRandomizer

get_logger = structlog.get_logger

# Дефолтные пороги случайной модели (в долях). Используются как фолбэк, если
# у кампании нет явных значений. Пользователь задаёт их ползунком — поля
# sticker_chance_percent / image_chance_percent (в процентах).
STICKER_CHANCE = 0.25
IMAGE_CHANCE = 0.40

# Экономия токенов: сколько ждём после заглушки, прежде чем проверить, что
# она ещё на месте (не удалена анти-спам ботом/модератором канала). Держим
# в диапазоне «задержки перед ответом на новый пост» конкурента (3-10с) —
# достаточно, чтобы бот-фильтр успел среагировать, но не растягивает
# публикацию надолго.
ECONOMY_PROBE_DELAY_SEC = 7
# Пул эмодзи для economy-пробника. Выбран нейтральный «позитивный реакт»
# набор — такие заглушки встречаются в живых чатах как самостоятельные
# реплики («👍» / «🔥» в ответ на пост). Раньше заглушкой были три цифры
# («4 1 7») — пользователь жаловался, что это выглядит странно, если ИИ-
# замена не успеет подтянуться (сначала «4 1 7», потом — коммент). Эмодзи
# и до подмены смотрится валидно.
_ECONOMY_STUB_EMOJI = ("👍", "🔥", "💯", "🙏", "✨", "😊", "🤔", "👀")


def stub_text(rng: random.Random) -> str:
    """Короткая нейтральная заглушка для economy-пробника (один эмодзи).

    Не несёт смысла специально — она одноразовая и либо живёт ~секунды до
    замены настоящим ИИ-текстом, либо палится фильтром канала (и тогда ИИ
    вообще не вызывается — в этом и экономия). Единичный эмодзи-реакт
    выглядит естественно в живой ленте комментариев, в отличие от прежних
    случайных цифр («4 1 7»)."""
    return rng.choice(_ECONOMY_STUB_EMOJI)


def _chance(campaign: Campaign, attr: str, default: float) -> float:
    """Вероятность (0..1) из поля-процента кампании; None/отсутствие → default."""
    val = getattr(campaign, attr, None)
    if val is None:
        return default
    return max(0, min(100, int(val))) / 100

# Юникод-диапазоны эмодзи (совпадают с worker/llm/style.py, реюзим оттуда,
# но локально держим свою функцию, чтобы не тянуть зависимость на приватку).
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x1F1E6, 0x1F1FF),
)


def _is_emoji(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _EMOJI_RANGES)


def strip_emoji(text: str) -> str:
    """Удаляет эмодзи и лишние пробелы. Safety net к LLM."""
    cleaned = "".join(ch for ch in text if not _is_emoji(ch))
    return " ".join(cleaned.split())


def emoji_prompt_suffix(campaign: Campaign) -> str:
    """Добавка к system prompt: явно просить LLM не использовать эмодзи."""
    if campaign.use_emojis:
        return ""
    return (
        "\n\nВажно: в ответе не используй эмодзи (никаких смайликов и "
        "пиктограмм — только слова, знаки препинания и цифры)."
    )


def apply_style(
    text: str,
    campaign: Campaign,
    persona: Any,
    style: StyleRandomizer,
) -> str:
    """Проход StyleRandomizer + safety net по эмодзи + потолок по словам."""
    result = style.randomize(text, persona)
    if not campaign.use_emojis:
        result = strip_emoji(result)
    from modules.commenting.worker import limits

    result = limits.truncate_words(result, getattr(campaign, "max_words", None))
    return result


# --- выбор способа доставки --------------------------------------------------


def pick_mode(
    campaign: Campaign,
    rng: random.Random,
    *,
    has_media: bool,
    has_sticker: bool,
) -> str:
    """Стикер | картинка | текст. Выбор детерминирован через rng.

    Стикер и картинка не сочетаются — стикер сам по себе.
    """
    if (
        campaign.use_stickers
        and has_sticker
        and rng.random() < _chance(campaign, "sticker_chance_percent", STICKER_CHANCE)
    ):
        return "sticker"
    if (
        campaign.attach_image
        and has_media
        and rng.random() < _chance(campaign, "image_chance_percent", IMAGE_CHANCE)
    ):
        return "text_with_image"
    return "text"


def campaign_media_ids(session, campaign_id: int) -> list[int]:
    """Id картинок кампании — ТОЛЬКО image/*.

    Defense-in-depth: API уже отсекает не-картинки при линковке
    (PUT /campaigns/{id}/media), но это фильтрует и то, что могло прилипнуть
    раньше (до фикса) — не даём случайному документу/видео уйти в коммент.
    """
    from sqlalchemy import select

    from core.models.media_asset import MediaAsset

    rows = session.execute(
        select(CampaignMediaAsset.media_asset_id)
        .join(MediaAsset, MediaAsset.id == CampaignMediaAsset.media_asset_id)
        .where(
            CampaignMediaAsset.campaign_id == campaign_id,
            MediaAsset.mime.like("image/%"),
        )
    ).scalars()
    return list(rows)


# mime → расширение, которое Telethon распознаёт как «картинка» (utils.is_image
# смотрит ТОЛЬКО на расширение файла — байты не сниффает вообще).
_IMAGE_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def _photo_file(data: bytes, mime: str) -> io.BytesIO:
    """Байты картинки как именованный BytesIO — чтобы Telethon отправил её

    ОБЫЧНЫМ сжатым фото, а не файлом-документом.

    Баг: Telethon решает photo-или-документ по ``utils.is_image(file)``, а та
    функция проверяет ТОЛЬКО расширение имени файла (``file.name``) — байты
    содержимого вообще не смотрит. ``force_document=False`` тут бессилен: при
    `file=<bytes>` без имени ``is_image()`` всегда возвращает False, и Telegram
    получает ``InputMediaUploadedDocument`` → показывает «unnamed, N МБ» вместо
    превью фото (баг-репорт «отправляет фото файлом, а должен обычным фото»).
    Присваиваем ``.name`` с правильным расширением — и Telethon сам сжимает
    фото под лимиты Telegram (как обычная отправка).
    """
    ext = _IMAGE_EXT_BY_MIME.get((mime or "").lower(), ".jpg")
    buf = io.BytesIO(data)
    buf.name = f"photo{ext}"
    return buf


def pick_media_bytes(session, campaign_id: int, rng: random.Random) -> Optional[tuple[bytes, str, str]]:
    """Случайная картинка кампании: (bytes, mime, filename) или None.

    Берём из БД одну строку сразу, не грузим все в память — картинки бывают
    большие.
    """
    from sqlalchemy import select

    from core.models.media_asset import MediaAsset

    ids = campaign_media_ids(session, campaign_id)
    if not ids:
        return None
    asset_id = rng.choice(ids)
    asset = session.execute(
        select(MediaAsset.bytes, MediaAsset.mime, MediaAsset.filename).where(
            MediaAsset.id == asset_id
        )
    ).first()
    if asset is None:
        return None
    return asset[0], asset[1], asset[2] or "image"


# --- стикеры аккаунта --------------------------------------------------------


# Сколько паков аккаунта обходим и сколько стикеров максимум собираем. Берём
# из ВСЕХ сохранённых паков (а не только первого) — так выбор разнообразнее и
# меньше повторов. Потолки держат число RPC и память в разумных рамках.
_MAX_STICKER_SETS = 12
_MAX_STICKERS = 400


async def load_account_stickers(ctx: dict, client, account_id: int) -> list:
    """Стикеры из ВСЕХ сохранённых паков аккаунта (кеш в ctx на время задачи).

    Раньше брали только первый пак — выбор всегда из одного набора. Теперь
    собираем стикеры по всем пакам (до ``_MAX_STICKER_SETS``), чтобы
    ``rng.choice(stickers)`` давал разнообразие. Пусто/ошибка → пустой список
    (стикеры не критичны, просто уйдёт текст).
    """
    cache = ctx.setdefault("_sticker_cache", {})
    if account_id in cache:
        return cache[account_id]

    from telethon.tl.functions.messages import GetAllStickersRequest, GetStickerSetRequest
    from telethon.tl.types import InputStickerSetID

    stickers: list = []
    try:
        all_sets = await around_telethon_call(
            lambda: client(GetAllStickersRequest(hash=0)),
            account_id=account_id,
            session_factory=ctx["session_factory"],
            publisher=ctx.get("publisher"),
            now=ctx.get("now"),
        )
        # Все версии telethon: sets — либо есть, либо (при NotModified) пусто.
        sets = getattr(all_sets, "sets", None) or []
        for st in sets[:_MAX_STICKER_SETS]:
            try:
                pack = await around_telethon_call(
                    lambda st=st: client(
                        GetStickerSetRequest(
                            stickerset=InputStickerSetID(id=st.id, access_hash=st.access_hash),
                            hash=0,
                        )
                    ),
                    account_id=account_id,
                    session_factory=ctx["session_factory"],
                    publisher=ctx.get("publisher"),
                    now=ctx.get("now"),
                )
            except Exception as exc:  # noqa: BLE001 — один пак не отдался, берём остальные
                get_logger().info(
                    "commenting.delivery.sticker_set_skipped",
                    account_id=account_id, error=repr(exc),
                )
                continue
            stickers.extend(getattr(pack, "documents", None) or [])
            if len(stickers) >= _MAX_STICKERS:
                stickers = stickers[:_MAX_STICKERS]
                break
    except Exception as exc:  # noqa: BLE001 - стикеры не критичны, просто не шлём
        get_logger().info(
            "commenting.delivery.stickers_unavailable",
            account_id=account_id, error=repr(exc),
        )
    cache[account_id] = stickers
    return stickers


# --- send_as (от имени канала) -----------------------------------------------


async def resolve_send_as(ctx: dict, client, account_id: int, discussion_group_id: int) -> Any:
    """Если аккаунт может писать от канала в этой группе — возвращаем peer.

    Кешируется на (account_id, group_id): getSendAs — обычный RPC, но лишний
    раз бить его на каждый коммент незачем.
    """
    cache = ctx.setdefault("_send_as_cache", {})
    key = (account_id, discussion_group_id)
    if key in cache:
        return cache[key]

    from telethon.tl.functions.channels import GetSendAsRequest

    try:
        result = await around_telethon_call(
            lambda: client(GetSendAsRequest(peer=discussion_group_id)),
            account_id=account_id,
            session_factory=ctx["session_factory"],
            publisher=ctx.get("publisher"),
            now=ctx.get("now"),
        )
        # Выбираем первый peer, отличный от самого аккаунта (обычно это канал).
        me_id = None
        try:
            me = await client.get_me()
            me_id = getattr(me, "id", None)
        except Exception:  # noqa: BLE001
            me_id = None
        peers = getattr(result, "peers", None) or []
        picked = None
        for p in peers:
            peer = getattr(p, "peer", p)
            pid = getattr(peer, "channel_id", None) or getattr(peer, "user_id", None) or getattr(peer, "chat_id", None)
            if pid is not None and pid != me_id:
                picked = peer
                break
        cache[key] = picked
        return picked
    except Exception as exc:  # noqa: BLE001
        get_logger().info(
            "commenting.delivery.send_as_unavailable",
            account_id=account_id, group_id=discussion_group_id, error=repr(exc),
        )
        cache[key] = None
        return None


# --- отправка ----------------------------------------------------------------


class Sent:
    """Простой контейнер вместо мокинга Telethon-типа."""

    __slots__ = ("id", "mode")

    def __init__(self, id: int, mode: str):
        self.id = id
        self.mode = mode


async def deliver_comment(
    ctx: dict,
    client,
    campaign: Campaign,
    *,
    account_id: int,
    discussion_group_id: int,
    text: str,
    reply_to: int,
    now,
    publisher,
    rng: random.Random,
) -> tuple[Any, str]:
    """Отправляет коммент выбранным способом. Возвращает (message, mode).

    Мoде — 'text' | 'text_with_image' | 'sticker'. При неуспехе стикера/
    картинки откатывается к тексту — коммент не пропадает.
    """
    session_factory = ctx["session_factory"]

    has_media = False
    if campaign.attach_image:
        with session_factory() as session:
            has_media = bool(campaign_media_ids(session, campaign.id))

    stickers: list = []
    if campaign.use_stickers:
        stickers = await load_account_stickers(ctx, client, account_id)

    mode = pick_mode(campaign, rng, has_media=has_media, has_sticker=bool(stickers))

    # send_as (от имени канала) — только если аккаунт может.
    send_as = None
    if campaign.write_as_channel:
        send_as = await resolve_send_as(ctx, client, account_id, discussion_group_id)

    async def _call(factory):
        return await around_telethon_call(
            factory,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )

    if mode == "sticker" and stickers:
        try:
            sticker = rng.choice(stickers)
            await _call(
                lambda: client.send_file(
                    discussion_group_id,
                    file=sticker,
                    reply_to=reply_to,
                    send_as=send_as,
                )
            )
            # Telegram НЕ поддерживает caption на стикерах — текст уходит
            # отдельным сообщением следом. Без этого ИИ-коммент оплачивался
            # (LLM-вызов) и писался в CommentLog как posted, но реально в
            # чат никогда не попадал — баг-репорт «комент отображается
            # только в логах, а в чате только стикер».
            sent = await _call(
                lambda: client.send_message(
                    discussion_group_id, text, reply_to=reply_to, send_as=send_as
                )
            )
            return sent, "sticker"
        except Exception as exc:  # noqa: BLE001 - откат в текст
            get_logger().info(
                "commenting.delivery.sticker_failed_fallback_text",
                account_id=account_id, error=repr(exc),
            )
            mode = "text"

    if mode == "text_with_image":
        with session_factory() as session:
            picked = pick_media_bytes(session, campaign.id, rng)
        if picked is not None:
            data, mime, name = picked
            # Подпись опциональна (image_caption_enabled): выключена — фото
            # уходит голым, без сгенерированного ИИ-текста.
            caption = text if campaign.image_caption_enabled else None
            # Именованный BytesIO — иначе Telethon не распознаёт картинку и
            # шлёт её файлом-документом (is_image() смотрит только на имя).
            photo_file = _photo_file(data, mime)
            try:
                sent = await _call(
                    lambda: client.send_file(
                        discussion_group_id,
                        file=photo_file,
                        caption=caption,
                        reply_to=reply_to,
                        force_document=False,
                        attributes=None,
                        send_as=send_as,
                    )
                )
                return sent, "text_with_image"
            except Exception as exc:  # noqa: BLE001 - откат в текст
                get_logger().info(
                    "commenting.delivery.image_failed_fallback_text",
                    account_id=account_id, error=repr(exc),
                )

    sent = await _call(
        lambda: client.send_message(
            discussion_group_id, text, reply_to=reply_to, send_as=send_as
        )
    )
    return sent, "text"


# --- экономия токенов (стаб → проверка → замена на ИИ-текст) ----------------


async def deliver_economy(
    ctx: dict,
    client,
    campaign: Campaign,
    *,
    account_id: int,
    discussion_group_id: int,
    reply_to: int,
    now,
    publisher,
    rng: random.Random,
    generate_real: Callable[[], Awaitable[str]],
) -> tuple[Any, str, str]:
    """Economy-режим: короткая заглушка → пауза → проверка → замена текстом.

    1. Шлём короткую нейтральную заглушку (``stub_text``) — без единого
       LLM-вызова.
    2. Ждём ``ECONOMY_PROBE_DELAY_SEC`` — анти-спам бот/модератор канала
       успевает среагировать, если умеет.
    3. Если заглушка всё ещё на месте — ТОЛЬКО ТЕПЕРЬ зовём ``generate_real``
       (платный LLM-вызов) и подменяем текст сообщения на реальный коммент
       (``edit_message`` — отправка нового сообщения не нужна).
    4. Если заглушку удалили — ИИ вообще не вызывается, токены сэкономлены.

    Ограничение: итоговый коммент всегда ТЕКСТОВЫЙ — стикер/картинка не
    применяются (Telegram не даёт поменять тип уже отправленного сообщения,
    а отправлять заглушку сразу стикером/фото бессмысленно — сам стаб должен
    быть maximally дешёвым и неприметным).

    Возвращает ``(sent_message, mode, final_text)``, где ``mode`` —
    ``economy_passed`` (заменили на ИИ-текст) | ``economy_failed`` (заглушку
    удалили, ИИ не вызывался) | ``economy_edit_failed`` (заменить не удалось,
    заглушка осталась висеть как есть).
    """
    session_factory = ctx["session_factory"]
    stub = stub_text(rng)
    log = get_logger()

    async def _call(factory):
        return await around_telethon_call(
            factory,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )

    sent = await _call(
        lambda: client.send_message(discussion_group_id, stub, reply_to=reply_to)
    )

    await asyncio.sleep(ECONOMY_PROBE_DELAY_SEC)

    try:
        messages = await _call(
            lambda: client.get_messages(discussion_group_id, ids=[sent.id])
        )
        found = messages[0] if isinstance(messages, (list, tuple)) else messages
        still_there = found is not None
    except Exception as exc:  # noqa: BLE001 — не смогли проверить: считаем, что прошло
        log.info(
            "commenting.delivery.economy_probe_check_failed",
            account_id=account_id, error=repr(exc),
        )
        still_there = True

    if not still_there:
        log.info("commenting.delivery.economy_probe_failed", account_id=account_id)
        return sent, "economy_failed", stub

    real_text = await generate_real()
    try:
        await _call(
            lambda: client.edit_message(discussion_group_id, sent.id, real_text)
        )
    except Exception as exc:  # noqa: BLE001 — заглушка уже висит, оставим как есть
        log.info(
            "commenting.delivery.economy_edit_failed",
            account_id=account_id, error=repr(exc),
        )
        return sent, "economy_edit_failed", stub
    return sent, "economy_passed", real_text


# --- пересылка готовых постов из внешнего @PostBot ---------------------------


DEFAULT_POSTBOT_USERNAME = "PostBot"


async def deliver_postbot(
    ctx: dict,
    client,
    campaign: Campaign,
    *,
    account_id: int,
    discussion_group_id: int,
    reply_to: int,
    now,
    publisher,
    rng: random.Random,
) -> tuple[Any, str, int]:
    """Публикует под постом готовый пост из @PostBot вместо ИИ-комментария.

    Берём случайный id из ``campaign.postbot_message_ids`` (сообщения из
    чата аккаунта с ботом — заранее подготовленные пользователем), копируем
    его содержимое (текст и/или медиа) и шлём РЕПЛАЕМ в обсуждение. Это не
    Telegram-"forward" (не показывает «Переслано от»): нужен именно reply в
    треде обсуждения, а forward такого не умеет. ИИ-токены не тратятся,
    промт/фото кампании не используются.

    Бросает исключение, если бот/сообщение недоступны (аккаунт никогда не
    писал боту, сообщение удалено и т.п.) — вызывающий код обрабатывает это
    как обычную ошибку доставки.
    """
    if not campaign.postbot_message_ids:
        raise ValueError("postbot_message_ids is empty")
    msg_id = rng.choice(campaign.postbot_message_ids)
    bot_username = campaign.postbot_username or DEFAULT_POSTBOT_USERNAME

    async def _call(factory):
        return await around_telethon_call(
            factory,
            account_id=account_id,
            session_factory=ctx["session_factory"],
            publisher=publisher,
            now=now,
        )

    source_messages = await _call(
        lambda: client.get_messages(bot_username, ids=[int(msg_id)])
    )
    source = (
        source_messages[0]
        if isinstance(source_messages, (list, tuple))
        else source_messages
    )
    if source is None:
        raise ValueError(f"postbot message #{msg_id} not found (bot={bot_username})")

    if getattr(source, "media", None) is not None:
        sent = await _call(
            lambda: client.send_file(
                discussion_group_id,
                file=source,
                caption=source.text or None,
                reply_to=reply_to,
            )
        )
    else:
        body = source.text or source.message or ""
        sent = await _call(
            lambda: client.send_message(discussion_group_id, body, reply_to=reply_to)
        )
    return sent, "postbot", int(msg_id)
