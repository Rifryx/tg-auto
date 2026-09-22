"""Пользовательские команды бота (этап 13b).

Команды доступны любому пользователю (в отличие от ``/admin26``):

* ``/start`` — приветствие + краткая инструкция.
* ``/help``  — список команд.
* ``/status``— сводка парка: сколько где, средний ban_risk, автопилот.

Все команды read-only: ничего не меняют, только показывают состояние.
Изменяющие действия (retire/throttle) остаются в Mini App, чтобы не плодить
дублирующую логику авторизации по чат-командам.
"""
from __future__ import annotations

from typing import Optional

from aiogram.types import Message
from sqlalchemy import func, select

from api.deps.db import _session_factory
from core.models import Account, AutopilotAction, AutopilotGoal, BanRiskSnapshot


_ACTIVE_STATUSES = ("pool", "assigned", "warming", "cooldown")


async def cmd_start(message: Message) -> None:
    """Приветствие: коротко объяснить бота и предложить открыть Mini App."""
    await message.answer(
        "👋 Привет! Я служебный бот для управления Telegram-аккаунтами.\n\n"
        "Доступные команды:\n"
        "• /status — сводка по парку\n"
        "• /help — все команды\n\n"
        "Полное управление — в Mini App.",
    )


async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Команды</b>\n"
        "• /start — начать работу\n"
        "• /status — сводка парка\n"
        "• /help — эта справка\n",
        parse_mode="HTML",
    )


async def cmd_status(message: Message) -> None:
    """Сводка парка: по статусам, средний ban_risk, автопилот-цели."""
    text = await _render_status()
    await message.answer(text, parse_mode="HTML")


async def _render_status() -> str:
    with _session_factory()() as session:
        # По статусам.
        rows = session.execute(
            select(Account.status, func.count()).group_by(Account.status)
        ).all()
        by_status: dict[str, int] = {r[0]: r[1] for r in rows}
        total_active = sum(by_status.get(s, 0) for s in _ACTIVE_STATUSES)

        # Средний ban_risk по активным.
        avg_risk_row = session.execute(
            select(func.avg(BanRiskSnapshot.risk_score))
            .join(Account, Account.id == BanRiskSnapshot.account_id)
            .where(Account.status.in_(_ACTIVE_STATUSES))
        ).scalar_one()
        avg_risk = float(avg_risk_row) if avg_risk_row is not None else 0.0

        # Autopilot: сколько включённых целей и сколько действий за 24ч.
        enabled_goals = int(
            session.execute(
                select(func.count())
                .select_from(AutopilotGoal)
                .where(AutopilotGoal.enabled.is_(True))
            ).scalar_one()
        )
        actions_last = int(
            session.execute(
                select(func.count()).select_from(AutopilotAction)
            ).scalar_one()
        )

    lines = ["<b>Сводка парка</b>"]
    if by_status:
        # Порядок: pool, assigned, warming, cooldown, created, retired, banned.
        for status in (
            "pool",
            "assigned",
            "warming",
            "cooldown",
            "created",
            "retired",
            "banned",
        ):
            count = by_status.get(status, 0)
            if count:
                lines.append(f"• {_pretty_status(status)}: <code>{count}</code>")
    else:
        lines.append("• Аккаунтов пока нет.")

    lines.append(
        f"\n<b>Активных:</b> <code>{total_active}</code>"
    )
    lines.append(f"<b>Средний риск бана:</b> <code>{round(avg_risk * 100)}/100</code>")
    lines.append(
        f"<b>Автопилот:</b> {_pretty_autopilot(enabled_goals, actions_last)}"
    )
    return "\n".join(lines)


def _pretty_status(status: str) -> str:
    return {
        "pool": "В пуле",
        "assigned": "Назначены",
        "warming": "На прогреве",
        "cooldown": "На охлаждении",
        "created": "Только созданы",
        "retired": "Выведены",
        "banned": "Забанены",
    }.get(status, status)


def _pretty_autopilot(enabled_goals: int, total_actions: int) -> str:
    if enabled_goals == 0:
        return "выключен (нет целей)"
    return f"{enabled_goals} целей, всего решений: <code>{total_actions}</code>"
