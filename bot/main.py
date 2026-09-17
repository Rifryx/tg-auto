"""Telegram-бот (aiogram v3): чат-команды владельца сервиса.

Ключевая команда: ``/admin26`` — открывает админ-меню, но ТОЛЬКО для
пользователей из ``ADMIN_USER_IDS``. Для остальных команда молча игнорируется:
бот не отвечает даже «команда не найдена» — так факт существования админки не
подтверждается посторонним, даже если кто-то узнал название.

Защита от подмены:
* ``message.from_user.id`` берётся из апдейта Telegram — этот источник считаем
  доверенным (мы контролируем bot-token и обмениваемся с Telegram по TLS).
* Список админов лежит в ENV; правки в БД не дают админ-прав.
* Все действия пишутся в аудит-лог (``core.audit.admin_action``).

Запуск локально:
    python -m bot.main
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from api.deps.db import _session_factory  # тестируемый и уже настроенный фабрик
from core.audit import admin_action
from core.config import get_settings
from core.models.account import Account
from core.models.subscription import Subscription
from core.repositories.subscription import SubscriptionRepository

logger = logging.getLogger("bot")
ADMIN_MENU_CB = "admin_menu"


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return str(user_id) in get_settings().admin_ids


# ---------------------------- /admin26 ---------------------------------------


async def cmd_admin(message: Message) -> None:
    """/admin26 — если пользователь в белом списке, показать меню; иначе молчим."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        # ВАЖНО: не отправляем «доступ запрещён» — это уже утечка факта.
        return

    admin_action(str(message.from_user.id), "open_admin_menu")

    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data=f"{ADMIN_MENU_CB}:stats")
    kb.button(text="🧾 Подписки", callback_data=f"{ADMIN_MENU_CB}:subs")
    kb.adjust(1)
    await message.answer(
        "<b>Админ-меню</b>\nВыберите действие.",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


# ---------------------------- callbacks --------------------------------------


async def on_admin_callback(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        # На всякий случай ещё раз — вдруг клавиатура утекла в форвард.
        await cb.answer("Not Found", show_alert=False)
        return
    if not cb.data or not cb.data.startswith(ADMIN_MENU_CB + ":"):
        return
    action = cb.data.split(":", 1)[1]

    if action == "stats":
        text = await _render_stats()
    elif action == "subs":
        text = await _render_subs()
    else:
        text = "Неизвестное действие."

    admin_action(str(cb.from_user.id), f"admin_menu:{action}")
    if cb.message:
        await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


async def _render_stats() -> str:
    with _session_factory()() as session:
        users = int(session.execute(select(func.count()).select_from(Subscription)).scalar_one())
        pro = int(
            session.execute(
                select(func.count()).select_from(Subscription).where(
                    Subscription.plan_id == "pro"
                )
            ).scalar_one()
        )
        accounts = int(session.execute(select(func.count()).select_from(Account)).scalar_one())
    return (
        "<b>Статистика</b>\n"
        f"Пользователей: <code>{users}</code>\n"
        f"Из них Pro:    <code>{pro}</code>\n"
        f"Аккаунтов TG:  <code>{accounts}</code>"
    )


async def _render_subs() -> str:
    with _session_factory()() as session:
        rows = list(
            session.execute(
                select(Subscription).order_by(Subscription.updated_at.desc()).limit(20)
            ).scalars()
        )
    if not rows:
        return "Подписок ещё нет."
    lines = ["<b>Последние подписки</b>"]
    for s in rows:
        lines.append(f"• <code>{s.user_id}</code> — {s.plan_id}")
    return "\n".join(lines)


# ---------------------------- entrypoint -------------------------------------


async def _amain() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    if not settings.admin_ids:
        # Не критично, но громкое предупреждение — иначе /admin26 никому не ответит.
        logger.warning("ADMIN_USER_IDS is empty — no one will be able to open /admin26")

    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher()

    dp.message.register(cmd_admin, Command("admin26"))
    dp.callback_query.register(on_admin_callback, F.data.startswith(ADMIN_MENU_CB + ":"))

    logger.info("bot starting (long-polling)…")
    await dp.start_polling(bot, handle_signals=True)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
