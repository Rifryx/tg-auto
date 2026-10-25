"""Live Interception — ответ ботов шиллинга на реплай живого пользователя.

Фича из «конкурентного анализа»: если в целевом чате участник отвечает
реплаем на реплику любого бот-аккаунта активной кампании, боты не молчат —
подхватывают контекст и отвечают через LLM, как если бы это был продолжающийся
диалог. Включается `campaign.auto_responder != "off"`.

Защиты от неадекватного поведения:
 - Не отвечаем на сообщения СВОИХ же ботов (anti-infinite loop): известные
   account_user_ids мы знаем через ClientPool.
 - Rate-limit per (campaign_id, sender_user_id): не больше ``_MAX_REPLIES`` в
   окне ``_RATE_WINDOW_SEC`` (Redis-ключ). Защищает от юзера, который будет
   упорно спамить реплаями, пытаясь сломать бота.
 - Timeout: если наш последний пост в этот чат старше ``_STALE_HOURS`` часов,
   не отвечаем — старый тред, выглядит как «бот ожил из гроба».
 - Отвечает тот же бот, чьё сообщение зацепил юзер (а не случайный) — так
   диалог остаётся осмысленным.

LLM-контекст: product.description + последние несколько сообщений треда.

Регистрация: класс ``LiveInterceptionRegistry`` держит по одному подключённому
слушателю на пару (campaign_id, account_id). Lifecycle через существующий
`campaign_lifecycle` канал Redis не прошит в этом PR — для MVP слушатели
поднимаются один раз на worker startup; attach/detach на лету — следующей
итерацией (когда появится критика от пользователя).
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from telethon import TelegramClient, events

from core.models.account import Account
from core.repositories.account import AccountRepository
from modules.shilling.models import ShillingCampaign, ShillingExecutionLog
from modules.shilling.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    ProductRepository,
)
from worker.llm import get_provider
from worker.llm.base import Message
from worker.tasks.logging import get_logger

_STALE_HOURS = 24
_RATE_WINDOW_SEC = 10 * 60
_MAX_REPLIES = 3
_HISTORY_LIMIT = 8  # сколько последних сообщений треда идёт в контекст
_LLM_SYSTEM = (
    "Ты — участник Telegram-чата, который только что обсуждал тему. "
    "Пользователь задал уточняющий вопрос реплаем на твоё сообщение. "
    "Ответь ЕСТЕСТВЕННО, одной короткой репликой (1–3 предложения), в стиле "
    "живой переписки. Никаких ссылок, @username, явной рекламы. Если уместно — "
    "косвенно обозначь продукт/бренд. Отвечай на том же языке, что и собеседник."
)


@dataclass
class _Handler:
    client: TelegramClient
    builder: Any  # telethon event handler callable
    event: events.NewMessage


class LiveInterceptionRegistry:
    """Реестр подключённых слушателей live-interception.

    key = (campaign_id, account_id). Значение — Telethon-handler, навешенный
    на клиент. При stop кампании вызываем ``detach_campaign`` для чистой
    отвязки — иначе остановленная кампания продолжит отвечать.
    """

    def __init__(self) -> None:
        self._handlers: dict[tuple[int, int], _Handler] = {}
        self._lock = asyncio.Lock()

    async def attach(self, ctx: dict, campaign: ShillingCampaign) -> int:
        """Подключить слушателей для всех аккаунтов кампании. Возвращает
        количество подключённых handler'ов (может быть 0, если нет аккаунтов)."""
        if campaign.auto_responder == "off":
            return 0
        if not campaign.enabled:
            return 0

        log = get_logger()
        pool = ctx["client_pool"]
        session_factory = ctx["session_factory"]
        with session_factory() as session:
            account_ids = [
                a.account_id
                for a in CampaignAccountRepository(session).list_by_campaign(campaign.id)
            ]
            # product_id → описание для LLM-контекста. Привязка product_id к
            # кампании уже проверена при сохранении (там идёт owner-check),
            # так что здесь безопасно достать по id.
            product_desc = ""
            if campaign.product_id is not None:
                product = ProductRepository(session).get(campaign.product_id)
                if product is not None:
                    product_desc = (product.description or "").strip()

        attached = 0
        async with self._lock:
            for account_id in account_ids:
                key = (campaign.id, account_id)
                if key in self._handlers:
                    continue
                try:
                    client = await pool.get(account_id)
                except Exception as exc:  # noqa: BLE001 — аккаунт недоступен, пропускаем
                    log.warning(
                        "shilling.live.attach_skip",
                        campaign_id=campaign.id,
                        account_id=account_id,
                        error=repr(exc),
                    )
                    continue
                handler = _build_handler(
                    ctx=ctx,
                    campaign=campaign,
                    account_id=account_id,
                    product_desc=product_desc,
                )
                event = events.NewMessage(incoming=True)
                client.add_event_handler(handler, event)
                self._handlers[key] = _Handler(client=client, builder=handler, event=event)
                attached += 1
        log.info(
            "shilling.live.attached", campaign_id=campaign.id, handlers=attached
        )
        return attached

    async def detach_campaign(self, campaign_id: int) -> int:
        """Отвязать все слушатели кампании. Возвращает количество снятых."""
        async with self._lock:
            keys = [k for k in self._handlers if k[0] == campaign_id]
            for key in keys:
                h = self._handlers.pop(key)
                try:
                    h.client.remove_event_handler(h.builder, h.event)
                except Exception:  # noqa: BLE001 — клиент уже мёртв / handler ушёл
                    pass
            return len(keys)

    def active_handlers(self) -> int:
        return len(self._handlers)


def _build_handler(
    *,
    ctx: dict,
    campaign: ShillingCampaign,
    account_id: int,
    product_desc: str,
):
    """Создаёт telethon-handler с замыканием на (campaign, account_id, ctx)."""
    log = get_logger()
    session_factory = ctx["session_factory"]
    redis = ctx.get("redis")
    pool = ctx["client_pool"]

    async def handler(event):  # type: ignore[no-untyped-def]
        try:
            await _handle_message(
                event=event,
                campaign=campaign,
                account_id=account_id,
                session_factory=session_factory,
                redis=redis,
                pool=pool,
                product_desc=product_desc,
            )
        except Exception as exc:  # noqa: BLE001 — любая ошибка handler'а не роняет Telethon
            log.warning(
                "shilling.live.handle_failed",
                campaign_id=campaign.id,
                account_id=account_id,
                error=repr(exc),
            )

    return handler


async def _handle_message(
    *,
    event,
    campaign: ShillingCampaign,
    account_id: int,
    session_factory,
    redis,
    pool,
    product_desc: str,
) -> None:
    """Основная логика: это ли reply на наше сообщение, можно ли ответить, LLM, отправка."""
    msg = event.message
    if msg is None or msg.reply_to_msg_id is None:
        return  # нас интересуют только reply на кого-то

    sender = await event.get_sender()
    if sender is None:
        return
    sender_id = getattr(sender, "id", None)
    if sender_id is None:
        return

    # 1) Не отвечать на сообщения своих же ботов — anti-infinite loop.
    with session_factory() as session:
        our_user_ids = _campaign_bot_user_ids(session, campaign.id)
    if sender_id in our_user_ids:
        return

    # 2) Проверить, что reply именно на НАШЕГО бота этой кампании (log'ируем
    # отправленные posted_message_id в execution_logs).
    with session_factory() as session:
        is_ours = _is_our_message(
            session,
            campaign_id=campaign.id,
            chat_id=int(event.chat_id),
            replied_message_id=int(msg.reply_to_msg_id),
            responder_account_id=account_id,
        )
    if not is_ours:
        return

    # 3) Rate-limit per (campaign, sender).
    if redis is not None:
        key = f"shilling:live:rl:{campaign.id}:{sender_id}"
        try:
            cnt = await redis.incr(key)
            if cnt == 1:
                await redis.expire(key, _RATE_WINDOW_SEC)
            if int(cnt) > _MAX_REPLIES:
                return  # слишком часто — молчим
        except Exception:  # noqa: BLE001 — Redis недоступен — просто продолжаем
            pass

    # 4) Собираем контекст (последние несколько сообщений в треде).
    history = await _collect_context(event, limit=_HISTORY_LIMIT)

    # 5) LLM.
    reply_text = await _generate_reply(
        campaign=campaign,
        product_desc=product_desc,
        current_message=msg.message or "",
        history=history,
    )
    if not reply_text:
        return

    # 6) Задержка «чтения», как в основном сценарии — чтобы не отвечать мгновенно.
    delay = random.uniform(
        float(campaign.reply_delay_min_sec),
        float(max(campaign.reply_delay_min_sec, campaign.reply_delay_max_sec)),
    )
    await asyncio.sleep(delay)

    # 7) Отправка reply от нашего бот-аккаунта (того же, кто получил reply).
    try:
        client = await pool.get(account_id)
    except Exception:  # noqa: BLE001
        return
    await client.send_message(event.chat_id, reply_text, reply_to=msg.id)
    get_logger().info(
        "shilling.live.replied",
        campaign_id=campaign.id,
        account_id=account_id,
        chat_id=int(event.chat_id),
    )


def _campaign_bot_user_ids(session, campaign_id: int) -> set[int]:
    """Telegram user_id'ы всех аккаунтов, подключённых к кампании."""
    repo = CampaignAccountRepository(session)
    account_ids = [a.account_id for a in repo.list_by_campaign(campaign_id)]
    if not account_ids:
        return set()
    rows = session.execute(
        select(Account.id, Account.user_id).where(Account.id.in_(account_ids))
    ).all()
    result: set[int] = set()
    for _acc_id, user_id in rows:
        if user_id is not None:
            try:
                result.add(int(user_id))
            except (TypeError, ValueError):
                continue
    return result


def _is_our_message(
    session,
    *,
    campaign_id: int,
    chat_id: int,
    replied_message_id: int,
    responder_account_id: int,
) -> bool:
    """True, если сообщение ``replied_message_id`` в чате ``chat_id`` было
    отправлено этой кампанией от аккаунта ``responder_account_id`` (и живее
    ``_STALE_HOURS``). Проверяется по execution_logs.posted_message_id."""
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(hours=_STALE_HOURS)
    stmt = (
        select(ShillingExecutionLog.id)
        .where(
            ShillingExecutionLog.campaign_id == campaign_id,
            ShillingExecutionLog.account_id == responder_account_id,
            ShillingExecutionLog.posted_message_id == replied_message_id,
            ShillingExecutionLog.created_at >= cutoff,
            ShillingExecutionLog.status == "sent",
        )
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none() is not None


async def _collect_context(event, limit: int) -> list[tuple[str, str]]:
    """Собрать `limit` последних сообщений в треде этого reply.

    Возвращает список (sender_label, text) — ``sender_label`` только для
    различения говорящих в промпте («А:» / «Б:»), не настоящие ники.
    """
    msgs = []
    try:
        # Берём несколько сообщений вокруг replied_to и само сообщение.
        async for m in event.client.iter_messages(event.chat_id, limit=limit, max_id=event.message.id):
            msgs.append(m)
    except Exception:  # noqa: BLE001 — не критично, работаем на текущем
        pass
    msgs = list(reversed(msgs))
    labels: dict[int, str] = {}
    out: list[tuple[str, str]] = []
    for m in msgs:
        sender_id = getattr(m, "sender_id", None) or 0
        if sender_id not in labels:
            labels[sender_id] = chr(ord("А") + len(labels) % 26)
        txt = (m.message or "").strip()
        if txt:
            out.append((labels[sender_id], txt))
    return out


async def _generate_reply(
    *,
    campaign: ShillingCampaign,
    product_desc: str,
    current_message: str,
    history: list[tuple[str, str]],
) -> Optional[str]:
    """LLM-ответ на реплай живого пользователя."""
    provider = get_provider(campaign.llm_provider)
    ctx_lines = ["Контекст предыдущих сообщений:"]
    for who, txt in history:
        ctx_lines.append(f"{who}: {txt}")
    ctx_lines.append("")
    ctx_lines.append(f"Пользователь ответил тебе: {current_message!r}")
    if product_desc:
        ctx_lines.append("")
        ctx_lines.append("Фоновая информация о продукте (не вставляй дословно):")
        ctx_lines.append(product_desc)
    if campaign.brand_name:
        ctx_lines.append(f"Бренд (если уместно упомянуть): {campaign.brand_name}")
    user_prompt = "\n".join(ctx_lines)

    try:
        raw = await provider.generate(
            system=_LLM_SYSTEM,
            messages=[Message(role="user", content=user_prompt)],
            max_tokens=300,
            temperature=0.9,
        )
    except Exception as exc:  # noqa: BLE001 — LLM недоступен — молчим
        get_logger().warning("shilling.live.llm_failed", error=repr(exc))
        return None
    text = (raw or "").strip()
    # Убираем кавычки, которые часто навязывает LLM вокруг «реплики».
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith('«') and text.endswith('»')
    ):
        text = text[1:-1].strip()
    return text or None
