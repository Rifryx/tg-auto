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

import random
from typing import Any, Optional

import structlog

from modules.commenting.models import Campaign, CampaignMediaAsset
from worker.health import around_telethon_call
from worker.llm import StyleRandomizer

get_logger = structlog.get_logger

# Пороги случайной модели. Проверялись руками: не хотим спамить каждым
# комментом стикером или картинкой, но и не хотим, чтобы флаг ощущался
# декоративным.
STICKER_CHANCE = 0.25
IMAGE_CHANCE = 0.40

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
    """Проход StyleRandomizer + safety net по эмодзи."""
    result = style.randomize(text, persona)
    if not campaign.use_emojis:
        result = strip_emoji(result)
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
    if campaign.use_stickers and has_sticker and rng.random() < STICKER_CHANCE:
        return "sticker"
    if campaign.attach_image and has_media and rng.random() < IMAGE_CHANCE:
        return "text_with_image"
    return "text"


def campaign_media_ids(session, campaign_id: int) -> list[int]:
    from sqlalchemy import select

    rows = session.execute(
        select(CampaignMediaAsset.media_asset_id).where(
            CampaignMediaAsset.campaign_id == campaign_id
        )
    ).scalars()
    return list(rows)


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


async def load_account_stickers(ctx: dict, client, account_id: int) -> list:
    """Первый стикер-пак аккаунта (кешируется в ctx на время задачи).

    Если пак пуст или запросить не удалось — возвращает пустой список.
    Дальше используется для случайного выбора: `rng.choice(stickers)`.
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
        if not sets:
            cache[account_id] = stickers
            return stickers
        first_set = sets[0]
        pack = await around_telethon_call(
            lambda: client(
                GetStickerSetRequest(
                    stickerset=InputStickerSetID(id=first_set.id, access_hash=first_set.access_hash),
                    hash=0,
                )
            ),
            account_id=account_id,
            session_factory=ctx["session_factory"],
            publisher=ctx.get("publisher"),
            now=ctx.get("now"),
        )
        stickers = list(getattr(pack, "documents", None) or [])
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
            sent = await _call(
                lambda: client.send_file(
                    discussion_group_id,
                    file=sticker,
                    reply_to=reply_to,
                    send_as=send_as,
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
            try:
                sent = await _call(
                    lambda: client.send_file(
                        discussion_group_id,
                        file=data,
                        caption=text,
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
