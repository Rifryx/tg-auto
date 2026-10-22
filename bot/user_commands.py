"""Пользовательские команды бота (этап 13b + расширение «15 команд в чате»).

Цель расширения: дать оператору делать типовые проверки и несколько
экстренных действий прямо в чате с ботом, не открывая Mini App. Команды
делятся на два уровня:

* Публичные (доступны любому, кто пишет боту) — read-only сводки:
  ``/status``, ``/campaigns``, ``/parsing``, ``/atrisk``, ``/proxies``,
  ``/autopilot``, ``/plan``, ``/flood``, ``/support``.
* Админские (белый список ``ADMIN_USER_IDS``, см. ``bot.auth.is_admin``;
  для остальных — молчим, как и ``/admin26``, чтобы не подтверждать факт
  существования команды): ``/find``, ``/broadcast``, ``/pause_all``.

Персональный скоуп: аккаунты (``Account``) — общий парк оператора (single-
tenant, см. docstring ``bot.notifier``), поэтому /status, /atrisk, /proxies,
/flood показывают данные по всему парку. А вот кампании, парсинг-задачи,
автопилот-цели и подписка персональны (``owner_user_id``/``user_id`` на
соответствующих моделях) — там фильтруем по отправителю команды, как и в
Mini App (``require_user``).
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram.types import Message
from sqlalchemy import func, select

from api.deps.db import _session_factory
from bot.auth import is_admin
from core.billing.plans import PLANS, is_unlimited
from core.models import (
    Account,
    AccountHealth,
    AppUser,
    AutopilotAction,
    AutopilotGoal,
    BanRiskSnapshot,
    Proxy,
    Subscription,
)
from core.repositories.account_health import AccountHealthRepository
from core.repositories.subscription import SubscriptionRepository
from core.repositories.support import SupportRepository
from modules.commenting.models import Campaign, CommentLog
from modules.parsing.models import ParsingJob
from modules.parsing.repositories.job import ParsingJobRepository


_ACTIVE_STATUSES = ("pool", "assigned", "warming", "cooldown")


def _arg(message: Message) -> str:
    """Текст команды без ``/command`` и без упоминания бота (``@bot``)."""
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def cmd_start(message: Message) -> None:
    """Приветствие: коротко объяснить бота и предложить открыть Mini App."""
    await message.answer(
        "👋 Привет! Я служебный бот для управления Telegram-аккаунтами.\n\n"
        "Самое частое — прямо здесь, в чате:\n"
        "• /status — сводка по парку\n"
        "• /campaigns — мои кампании нейрокомментинга\n"
        "• /help — все команды\n\n"
        "Полное управление — в Mini App.",
    )


async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Команды</b>\n\n"
        "<b>Сводки</b>\n"
        "• /status — сводка парка аккаунтов\n"
        "• /campaigns — мои кампании нейрокомментинга\n"
        "• /parsing — мои последние задачи парсинга\n"
        "• /atrisk — аккаунты с низким health-score\n"
        "• /proxies — прокси-пул по статусам\n"
        "• /autopilot — мои цели автопилота\n"
        "• /flood — аккаунты на охлаждении/floodwait\n"
        "• /plan — мой тариф и лимиты\n\n"
        "<b>Прочее</b>\n"
        "• /support &lt;текст&gt; — написать в поддержку, не открывая Mini App\n"
        "• /start — начать работу\n"
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


# ─────────────────────────────────────────────────────────────────────────────
# Расширенные публичные команды (виден всем пишущим боту).
# ─────────────────────────────────────────────────────────────────────────────


async def cmd_campaigns(message: Message) -> None:
    """`/campaigns` — мои кампании нейрокомментинга (по owner_user_id)."""
    user_id = str(message.from_user.id) if message.from_user else ""
    if not user_id:
        return
    with _session_factory()() as session:
        rows = list(
            session.execute(
                select(Campaign)
                .where(Campaign.owner_user_id == user_id)
                .order_by(Campaign.updated_at.desc())
                .limit(20)
            ).scalars()
        )
        # Счётчик комментариев за сутки — по всему парку кампаний пользователя
        # (считаем по posted/failed/flagged — тем, что реально ушли в LLM).
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        posted_24h = 0
        if rows:
            posted_24h = int(
                session.execute(
                    select(func.count())
                    .select_from(CommentLog)
                    .where(
                        CommentLog.campaign_id.in_([c.id for c in rows]),
                        CommentLog.created_at >= since,
                        CommentLog.status == "posted",
                    )
                ).scalar_one()
            )

    if not rows:
        await message.answer(
            "Кампаний нет. Создайте первую в Mini App (раздел «Нейрокомментинг»)."
        )
        return

    lines = [f"<b>Мои кампании</b> ({len(rows)})"]
    lines.append(f"За 24 часа опубликовано: <code>{posted_24h}</code>")
    lines.append("")
    for c in rows[:10]:
        state = "🟢 вкл" if c.enabled else "⏸ пауза"
        lines.append(f"• #{c.id} <b>{html.escape(c.name)}</b> — {state}")
    if len(rows) > 10:
        lines.append(f"\n…и ещё {len(rows) - 10}")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_parsing(message: Message) -> None:
    """`/parsing` — последние задачи парсинга пользователя + их прогресс."""
    tg_id = message.from_user.id if message.from_user else None
    if tg_id is None:
        return
    with _session_factory()() as session:
        jobs = ParsingJobRepository(session).list_by_owner(int(tg_id), limit=10)
    if not jobs:
        await message.answer(
            "Задач парсинга нет. Создайте в Mini App → «Парсинг»."
        )
        return
    label = {
        "pending": "⏳ ожидает",
        "running": "▶️ работает",
        "paused": "⏸ пауза",
        "done": "✅ готово",
        "failed": "❌ ошибка",
        "stopped": "⏹ остановлено",
    }
    lines = [f"<b>Задачи парсинга</b> ({len(jobs)})"]
    for j in jobs:
        state = label.get(j.status, j.status)
        lines.append(
            f"• #{j.id} <b>{html.escape(j.name)}</b> — {state} · "
            f"собрано <code>{j.raw_count}</code> / добавлено <code>{j.inserted_count}</code>"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_atrisk(message: Message) -> None:
    """`/atrisk` — top-N аккаунтов с низким health-score (риск бана)."""
    with _session_factory()() as session:
        rows = AccountHealthRepository(session).list_at_risk(max_score=50, limit=10)
        acc_ids = [r.account_id for r in rows]
        accounts: dict[int, Account] = {}
        if acc_ids:
            for a in session.execute(
                select(Account).where(Account.id.in_(acc_ids))
            ).scalars():
                accounts[a.id] = a
    if not rows:
        await message.answer("✅ Все аккаунты с нормальным health-score (>50).")
        return
    lines = [f"<b>Аккаунты в зоне риска</b> ({len(rows)})"]
    for r in rows:
        a = accounts.get(r.account_id)
        tag = (
            f"@{a.username}" if a and a.username
            else (a.phone if a else f"#{r.account_id}")
        )
        lines.append(
            f"• #{r.account_id} {html.escape(tag)} — score <code>{r.health_score}</code>"
        )
    lines.append("\nИсправить — через Mini App → «Аккаунты».")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_proxies(message: Message) -> None:
    """`/proxies` — сводка прокси-пула по статусам (alive/dead/unchecked)."""
    with _session_factory()() as session:
        by_status: dict[str, int] = {
            r[0]: r[1]
            for r in session.execute(
                select(Proxy.status, func.count()).group_by(Proxy.status)
            ).all()
        }
    if not by_status:
        await message.answer("Прокси ещё не добавлены. Mini App → «Прокси».")
        return
    alive = by_status.get("alive", 0)
    dead = by_status.get("dead", 0)
    unchecked = by_status.get("unchecked", 0)
    total = alive + dead + unchecked
    lines = ["<b>Прокси-пул</b>"]
    lines.append(f"🟢 Живые: <code>{alive}</code>")
    lines.append(f"🔴 Мёртвые: <code>{dead}</code>")
    lines.append(f"⚪ Не проверены: <code>{unchecked}</code>")
    lines.append(f"<b>Всего:</b> <code>{total}</code>")
    if dead and alive:
        pct = round(dead / total * 100)
        if pct >= 30:
            lines.append(
                f"\n⚠️ {pct}% прокси мертвы — проверьте пул перед запуском кампаний."
            )
    await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_autopilot(message: Message) -> None:
    """`/autopilot` — цели автопилота пользователя и его решения за 24 часа."""
    user_id = str(message.from_user.id) if message.from_user else ""
    if not user_id:
        return
    with _session_factory()() as session:
        goals = list(
            session.execute(
                select(AutopilotGoal).where(AutopilotGoal.user_id == user_id)
            ).scalars()
        )
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        goal_ids = [g.id for g in goals]
        actions_24h = 0
        last_action: Optional[AutopilotAction] = None
        if goal_ids:
            actions_24h = int(
                session.execute(
                    select(func.count())
                    .select_from(AutopilotAction)
                    .where(
                        AutopilotAction.goal_id.in_(goal_ids),
                        AutopilotAction.created_at >= since,
                    )
                ).scalar_one()
            )
            last_action = session.execute(
                select(AutopilotAction)
                .where(AutopilotAction.goal_id.in_(goal_ids))
                .order_by(AutopilotAction.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
    if not goals:
        await message.answer(
            "Автопилот не настроен. Создайте цель в Mini App → «Автопилот»."
        )
        return
    enabled = sum(1 for g in goals if g.enabled)
    lines = ["<b>Автопилот</b>"]
    lines.append(f"Целей: <code>{len(goals)}</code> (вкл: <code>{enabled}</code>)")
    for g in goals[:5]:
        state = "✅" if g.enabled else "⏸"
        lines.append(f"• {state} <code>{g.goal_type}</code>")
    lines.append(f"\nРешений за 24ч: <code>{actions_24h}</code>")
    if last_action:
        when = last_action.created_at.strftime("%d.%m %H:%M") if last_action.created_at else "—"
        lines.append(
            f"Последнее: <code>{last_action.action_type}</code> "
            f"({last_action.status}) · {when}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_plan(message: Message) -> None:
    """`/plan` — мой тариф и ключевые лимиты."""
    user_id = str(message.from_user.id) if message.from_user else ""
    if not user_id:
        return
    with _session_factory()() as session:
        sub = SubscriptionRepository(session).get(user_id)
        plan_id = sub.plan_id if sub else "free"
        # Фактическое использование — ровно те метрики, что бьются о лимиты.
        accounts_used = int(
            session.execute(
                select(func.count())
                .select_from(Account)
                .where(Account.status.notin_(["retired", "banned"]))
            ).scalar_one()
        )
        campaigns_active = int(
            session.execute(
                select(func.count())
                .select_from(Campaign)
                .where(
                    Campaign.owner_user_id == user_id,
                    Campaign.enabled.is_(True),
                )
            ).scalar_one()
        )
    limits = PLANS.get(plan_id, PLANS["free"])

    def _show(v) -> str:
        return "∞" if is_unlimited(v) else str(v)

    lines = [f"<b>Тариф:</b> {plan_id.upper()}"]
    if sub and sub.expires_at:
        lines.append(f"Действует до: <code>{sub.expires_at.strftime('%d.%m.%Y')}</code>")
    lines.append("")
    lines.append("<b>Использование / лимит</b>")
    lines.append(
        f"• Аккаунтов: <code>{accounts_used} / {_show(limits['accounts_max'])}</code>"
    )
    lines.append(
        f"• Активных кампаний: <code>{campaigns_active} / "
        f"{_show(limits['campaigns_active_max'])}</code>"
    )
    lines.append(
        f"• Комментов в сутки: <code>{_show(limits['comments_per_day'])}</code>"
    )
    lines.append(
        f"• Каналов на мониторинге: <code>{_show(limits['channels_watch_max'])}</code>"
    )
    if plan_id == "free":
        lines.append(
            "\nПерейти на Pro — Mini App → «Тариф и лимиты»."
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_flood(message: Message) -> None:
    """`/flood` — аккаунты в cooldown (floodwait или ручная пауза)."""
    now = datetime.now(timezone.utc)
    with _session_factory()() as session:
        rows = list(
            session.execute(
                select(Account)
                .where(
                    Account.status == "cooldown",
                    Account.cooldown_until.is_not(None),
                )
                .order_by(Account.cooldown_until.asc())
                .limit(10)
            ).scalars()
        )
    if not rows:
        await message.answer("✅ Нет аккаунтов на cooldown.")
        return
    lines = [f"<b>Аккаунты на cooldown</b> ({len(rows)})"]
    for a in rows:
        remaining = (a.cooldown_until - now) if a.cooldown_until else None
        when = _format_remaining(remaining)
        tag = f"@{a.username}" if a.username else a.phone
        lines.append(f"• #{a.id} {html.escape(tag)} — ⏳ {when}")
    await message.answer("\n".join(lines), parse_mode="HTML")


def _format_remaining(delta) -> str:
    if delta is None:
        return "—"
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "истёк"
    if seconds < 3600:
        return f"{seconds // 60} мин"
    if seconds < 86400:
        return f"{seconds // 3600} ч"
    return f"{seconds // 86400} д"


async def cmd_support(message: Message) -> None:
    """`/support <текст>` — быстрый тикет в поддержку прямо из чата."""
    user_id = str(message.from_user.id) if message.from_user else ""
    if not user_id:
        return
    text = _arg(message)
    if not text:
        await message.answer(
            "Напишите так: <code>/support ваш текст</code>\n"
            "Или зайдите в Mini App → «Поддержка» для чата с историей.",
            parse_mode="HTML",
        )
        return
    if len(text) > 4000:
        await message.answer("Слишком длинное сообщение (лимит 4000 символов).")
        return
    with _session_factory()() as session:
        prof = session.get(AppUser, user_id)
        username = prof.username if prof is not None else (
            message.from_user.username if message.from_user else None
        )
        SupportRepository(session).add_message(
            user_id=user_id,
            direction="user",
            text=text,
            username=username,
        )
        session.commit()
    await message.answer(
        "✓ Отправлено в поддержку. Менеджер ответит здесь же, в чате."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Админские команды (ADMIN_USER_IDS). Для чужих — тихо игнорируем.
# ─────────────────────────────────────────────────────────────────────────────


async def cmd_find(message: Message) -> None:
    """`/find <q>` — найти аккаунт по id/phone/username. Только админ."""
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    q = _arg(message)
    if not q:
        await message.answer("Использование: <code>/find id|phone|@username</code>", parse_mode="HTML")
        return

    with _session_factory()() as session:
        acc: Optional[Account] = None
        if q.isdigit():
            acc = session.get(Account, int(q))
        if acc is None:
            cleaned = q.lstrip("@").strip()
            acc = session.execute(
                select(Account).where(
                    (Account.username == cleaned) | (Account.phone == cleaned)
                ).limit(1)
            ).scalar_one_or_none()
    if acc is None:
        await message.answer(f"Не нашёл: <code>{html.escape(q)}</code>", parse_mode="HTML")
        return
    tag = f"@{acc.username}" if acc.username else acc.phone
    lines = [f"<b>Аккаунт #{acc.id}</b> {html.escape(tag)}"]
    lines.append(f"Статус: <code>{acc.status}</code>")
    if acc.role:
        lines.append(f"Роль: <code>{acc.role}</code>")
    if acc.cooldown_until:
        lines.append(f"Cooldown до: <code>{acc.cooldown_until:%d.%m.%Y %H:%M}</code>")
    if acc.proxy_id:
        lines.append(f"Прокси: <code>#{acc.proxy_id}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_broadcast(message: Message) -> None:
    """`/broadcast <текст>` — рассылка всем админам (себе и остальным).

    Полный broadcast всем пользователям требует отдельных подтверждений и
    rate-limit'ов — не делаем из чата бота. Эта команда — быстрая заметка в
    админский круг (например, предупреждение о даунтайме перед миграцией).
    """
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    text = _arg(message)
    if not text:
        await message.answer(
            "Использование: <code>/broadcast текст</code>\n"
            "Пойдёт всем из ADMIN_USER_IDS.",
            parse_mode="HTML",
        )
        return
    from core.config import get_settings

    settings = get_settings()
    bot = message.bot
    sent = 0
    for chat_id in settings.admin_ids:
        try:
            await bot.send_message(
                int(chat_id),
                f"📢 <b>Админ-рассылка</b>\n\n{html.escape(text)}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:  # noqa: BLE001
            # Админ мог не писать боту — пропускаем молча.
            continue
    await message.answer(f"✓ Доставлено админам: {sent}/{len(settings.admin_ids)}")


async def cmd_pause_all(message: Message) -> None:
    """`/pause_all` — выключить все активные кампании нейрокомментинга (аварийный

    стоп). Только админ: это тяжёлое действие, пользователь может нажать это по
    ошибке через чат. Автопилот/прогрев это не трогает — только campaign.enabled.
    """
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    with _session_factory()() as session:
        rows = list(
            session.execute(
                select(Campaign).where(Campaign.enabled.is_(True))
            ).scalars()
        )
        if not rows:
            await message.answer("Нет включённых кампаний — ничего не трогаю.")
            return
        for c in rows:
            c.enabled = False
        session.commit()
    await message.answer(
        f"⏸ Остановил <code>{len(rows)}</code> кампаний (установил enabled=False).\n"
        "Включить обратно — поштучно в Mini App.",
        parse_mode="HTML",
    )
