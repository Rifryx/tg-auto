"""Общая проверка админ-доступа для чат-команд бота.

Вынесена из ``bot.main``, чтобы ``bot.user_commands`` могла её использовать
без циклического импорта (main импортирует команды из user_commands).
"""
from __future__ import annotations

from core.config import get_settings


def is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return str(user_id) in get_settings().admin_ids
