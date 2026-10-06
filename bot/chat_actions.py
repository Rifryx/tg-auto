"""Интерактивные команды чат-бота: управление праймингом, карантин
аккаунтов, биллинг — всё с проверкой владения (bot/actions.py).

Команды:
  /campaigns            — список своих прайминг-кампаний (кнопки управления)
  /pause <id>           — пауза кампании
  /resume <id>          — возобновить кампанию
  /stop <id>            — остановить кампанию
  /repeat [id]          — повторить кампанию (последнюю завершённую или id)
  /quarantine <id>      — вывести аккаунт из работы (обратимо)
  /unquarantine <id>    — вернуть аккаунт в пул
  /billing              — текущий тариф, срок, лимиты

Inline-callback'и (та же логика, тот же ownership):
  pc:open:<id>  pc:pause:<id>  pc:resume:<id>  pc:stop:<id>
  pc:repeat:<id>  pc:back  pc:noop
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from api.deps.db import _session_factory
from bot import actions
from core.billing.plans import PLANS, is_unlimited
from core.models.subscription import Subscription
from core.queue import TaskQueue

CB_PREFIX = "pc"  # priming-control callbacks


# --- форматирование -----------------------------------------------------------

_STATUS_LABEL = {
    "draft": "черновик",
    "queued": "в очереди",
    "running": "работает",
    "paused": "на паузе",
    "stopped": "остановлена",
    "finished": "завершена",
    "failed": "ошибка",
}
_STATUS_EMOJI = {
    "running": "▶️",
    "paused": "⏸",
    "stopped": "⏹",
    "finished": "✅",
    "failed": "⚠️",
    "draft": "📝",
    "queued": "🕐",
}


def _status_line(status: str) -> str:
    return f"{_STATUS_EMOJI.get(status, '•')} {_STATUS_LABEL.get(status, status)}"


def _require_uid(obj: Message | CallbackQuery) -> Optional[int]:
    return obj.from_user.id if obj.from_user else None


def _task_queue() -> TaskQueue:
    return TaskQueue()


# --- /campaigns ---------------------------------------------------------------


async def cmd_campaigns(message: Message) -> None:
    uid = _require_uid(message)
    if uid is None:
        return
    with _session_factory()() as session:
        camps = actions.list_owned_campaigns(session, uid)
    if not camps:
        await message.answer(
            "У вас пока нет прайминг-кампаний.\n"
            "Создайте первую в Mini App → раздел «Сервисы» → «Прайминг».",
        )
        return
    kb = InlineKeyboardBuilder()
    for c in camps:
        kb.button(
            text=f"{_STATUS_EMOJI.get(c.status, '•')} #{c.id} {c.name[:28]}",
            callback_data=f"{CB_PREFIX}:open:{c.id}",
        )
    kb.adjust(1)
    await message.answer(
        f"<b>Ваши кампании</b> ({len(camps)})\nВыберите для управления:",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


def _campaign_card(session, campaign_id: int, requester_id: int) -> tuple[str, object]:
    """Текст карточки кампании + inline-клавиатура действий."""
    camp = actions.get_owned_campaign(session, campaign_id, requester_id)
    counts = actions.campaign_counts(session, campaign_id)
    acc = counts["accounts"]
    tg = counts["targets"]
    lines = [
        f"<b>#{camp.id} — {camp.name}</b>",
        f"Статус: {_status_line(camp.status)}",
        f"Триггер: <code>{camp.trigger_action}</code>",
    ]
    acc_total = sum(acc.values())
    quar = acc.get("quarantined", 0)
    lines.append(
        f"Аккаунты: <code>{acc_total}</code>"
        + (f" (карантин {quar})" if quar else "")
    )
    primed = tg.get("primed", 0)
    pending = tg.get("pending", 0)
    failed = tg.get("failed", 0)
    lines.append(
        f"Цели: ✅ <code>{primed}</code> · ⏳ <code>{pending}</code>"
        + (f" · ⚠️ <code>{failed}</code>" if failed else "")
    )

    kb = InlineKeyboardBuilder()
    if camp.status == "running":
        kb.button(text="⏸ Пауза", callback_data=f"{CB_PREFIX}:pause:{camp.id}")
        kb.button(text="⏹ Стоп", callback_data=f"{CB_PREFIX}:stop:{camp.id}")
    elif camp.status in ("paused", "stopped"):
        kb.button(text="▶️ Возобновить", callback_data=f"{CB_PREFIX}:resume:{camp.id}")
        if camp.status == "paused":
            kb.button(text="⏹ Стоп", callback_data=f"{CB_PREFIX}:stop:{camp.id}")
    if camp.status in ("finished", "stopped", "paused"):
        kb.button(text="🔁 Повторить", callback_data=f"{CB_PREFIX}:repeat:{camp.id}")
    kb.button(text="‹ К списку", callback_data=f"{CB_PREFIX}:back")
    kb.adjust(2)
    return "\n".join(lines), kb.as_markup()


# --- текстовые команды управления ---------------------------------------------


def _parse_id(message: Message) -> Optional[int]:
    parts = (message.text or "").split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1].lstrip("#"))
    except ValueError:
        return None


async def cmd_pause(message: Message) -> None:
    await _simple_campaign_cmd(message, "pause")


async def cmd_resume(message: Message) -> None:
    await _simple_campaign_cmd(message, "resume")


async def cmd_stop(message: Message) -> None:
    await _simple_campaign_cmd(message, "stop")


async def _simple_campaign_cmd(message: Message, action: str) -> None:
    uid = _require_uid(message)
    if uid is None:
        return
    cid = _parse_id(message)
    if cid is None:
        await message.answer(f"Укажите id: <code>/{action} 12</code>", parse_mode="HTML")
        return
    try:
        with _session_factory()() as session:
            if action == "pause":
                camp = actions.do_pause(session, cid, uid)
            elif action == "resume":
                camp = await actions.do_resume(session, cid, uid, _task_queue())
            else:
                camp = actions.do_stop(session, cid, uid)
        await message.answer(
            f"Кампания #{cid} — {_status_line(camp.status)}.",
        )
    except actions.ActionError as exc:
        await message.answer(exc.user_msg)


async def cmd_repeat(message: Message) -> None:
    uid = _require_uid(message)
    if uid is None:
        return
    cid = _parse_id(message)  # опционально
    try:
        with _session_factory()() as session:
            clone, started = await actions.do_repeat(
                session, uid, _task_queue(), campaign_id=cid
            )
        if started:
            await message.answer(
                f"🔁 Создана копия #{clone.id} «{clone.name}» и запущена.",
            )
        else:
            await message.answer(
                f"🔁 Создана копия #{clone.id} «{clone.name}» (черновик).\n"
                "Запуск не прошёл автопроверку — доведите в Mini App.",
            )
    except actions.ActionError as exc:
        await message.answer(exc.user_msg)


# --- карантин аккаунтов -------------------------------------------------------


async def cmd_quarantine(message: Message) -> None:
    await _account_cmd(message, "quarantine")


async def cmd_unquarantine(message: Message) -> None:
    await _account_cmd(message, "unquarantine")


async def _account_cmd(message: Message, action: str) -> None:
    uid = _require_uid(message)
    if uid is None:
        return
    aid = _parse_id(message)
    if aid is None:
        await message.answer(f"Укажите id: <code>/{action} 42</code>", parse_mode="HTML")
        return
    try:
        with _session_factory()() as session:
            if action == "quarantine":
                acc = actions.quarantine_account(session, aid, uid)
                await message.answer(
                    f"🚧 Аккаунт #{aid} выведен из работы (статус «{acc.status}»).\n"
                    f"Вернуть: <code>/unquarantine {aid}</code>",
                    parse_mode="HTML",
                )
            else:
                acc = actions.unquarantine_account(session, aid, uid)
                await message.answer(
                    f"✅ Аккаунт #{aid} возвращён (статус «{acc.status}»).",
                )
    except actions.ActionError as exc:
        await message.answer(exc.user_msg)


# --- /billing -----------------------------------------------------------------


async def cmd_billing(message: Message) -> None:
    uid = _require_uid(message)
    if uid is None:
        return
    text = _render_billing(str(uid))
    await message.answer(text, parse_mode="HTML")


def _render_billing(user_id: str) -> str:
    with _session_factory()() as session:
        sub = session.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        ).scalar_one_or_none()
    plan_id = "pro" if (sub and sub.plan_id == "pro") else "free"
    limits = PLANS[plan_id]

    lines = [f"<b>Тариф: {plan_id.upper()}</b>"]
    if plan_id == "pro" and sub and sub.expires_at:
        exp = sub.expires_at
        now = datetime.now(timezone.utc)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        days = (exp - now).days
        lines.append(
            f"Действует до: <code>{exp.date().isoformat()}</code>"
            + (f" (ещё {days} дн.)" if days >= 0 else " (истёк)")
        )
    elif plan_id == "free":
        lines.append("Апгрейд до Pro — в Mini App → «Тариф и лимиты».")

    def fmt(v) -> str:
        if isinstance(v, bool):
            return "да" if v else "нет"
        if is_unlimited(v):
            return "∞"
        return str(v)

    lines.append("")
    lines.append("<b>Лимиты</b>")
    lines.append(f"• Аккаунтов: <code>{fmt(limits['accounts_max'])}</code>")
    lines.append(f"• Активных кампаний: <code>{fmt(limits['campaigns_active_max'])}</code>")
    lines.append(f"• Комментов/день: <code>{fmt(limits['comments_per_day'])}</code>")
    lines.append(f"• Прайминг: <code>{fmt(limits['priming_enabled'])}</code>")
    lines.append(f"• Поддержка: <code>{limits['support_level']}</code>")
    return "\n".join(lines)


# --- общий callback-роутер (из /campaigns И из notifier-алертов) --------------


async def on_control_callback(cb: CallbackQuery) -> None:
    uid = _require_uid(cb)
    if uid is None or not cb.data:
        await cb.answer()
        return
    parts = cb.data.split(":")
    if parts[0] != CB_PREFIX:
        return
    action = parts[1] if len(parts) > 1 else ""

    try:
        if action == "back":
            await _show_list(cb, uid)
            await cb.answer()
            return
        if action == "noop":
            await cb.answer()
            return

        cid = int(parts[2]) if len(parts) > 2 else None
        if cid is None:
            await cb.answer("Нет id", show_alert=False)
            return

        if action == "open":
            await _show_card(cb, cid, uid)
            await cb.answer()
        elif action == "pause":
            with _session_factory()() as s:
                actions.do_pause(s, cid, uid)
            await _show_card(cb, cid, uid)
            await cb.answer("Поставлено на паузу")
        elif action == "resume":
            with _session_factory()() as s:
                await actions.do_resume(s, cid, uid, _task_queue())
            await _show_card(cb, cid, uid)
            await cb.answer("Возобновлено")
        elif action == "stop":
            with _session_factory()() as s:
                actions.do_stop(s, cid, uid)
            await _show_card(cb, cid, uid)
            await cb.answer("Остановлено")
        elif action == "repeat":
            with _session_factory()() as s:
                clone, started = await actions.do_repeat(
                    s, uid, _task_queue(), campaign_id=cid
                )
            await cb.answer(
                f"Копия #{clone.id} " + ("запущена" if started else "как черновик"),
                show_alert=True,
            )
        else:
            await cb.answer()
    except actions.ActionError as exc:
        await cb.answer(exc.user_msg, show_alert=True)


async def _show_card(cb: CallbackQuery, cid: int, uid: int) -> None:
    with _session_factory()() as session:
        text, markup = _campaign_card(session, cid, uid)
    if cb.message:
        try:
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:  # noqa: BLE001 — если нельзя редактировать, шлём новым
            await cb.message.answer(text, parse_mode="HTML", reply_markup=markup)


async def _show_list(cb: CallbackQuery, uid: int) -> None:
    with _session_factory()() as session:
        camps = actions.list_owned_campaigns(session, uid)
    kb = InlineKeyboardBuilder()
    for c in camps:
        kb.button(
            text=f"{_STATUS_EMOJI.get(c.status, '•')} #{c.id} {c.name[:28]}",
            callback_data=f"{CB_PREFIX}:open:{c.id}",
        )
    kb.adjust(1)
    if cb.message:
        try:
            await cb.message.edit_text(
                f"<b>Ваши кампании</b> ({len(camps)})\nВыберите для управления:",
                parse_mode="HTML",
                reply_markup=kb.as_markup(),
            )
        except Exception:  # noqa: BLE001
            pass


def alert_keyboard(campaign_id: int, *, paused: bool):
    """Inline-клавиатура под push-алертом автопаузы: быстрые действия."""
    kb = InlineKeyboardBuilder()
    if paused:
        kb.button(
            text="▶️ Возобновить",
            callback_data=f"{CB_PREFIX}:resume:{campaign_id}",
        )
    kb.button(text="⏹ Остановить", callback_data=f"{CB_PREFIX}:stop:{campaign_id}")
    kb.button(text="🔎 Открыть", callback_data=f"{CB_PREFIX}:open:{campaign_id}")
    kb.adjust(2)
    return kb.as_markup()
