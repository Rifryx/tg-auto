"""Редактируемый из админки контент приложения (поверх app_settings).

Два раздела:
* ``about``   — блок «О приложении» (имя, версия, описание).
* ``support`` — конфиг поддержки: контакт менеджера (ссылка на ЛС) и флаг,
  включён ли чат поддержки внутри приложения.

У каждого раздела есть дефолт — чтобы приложение работало до первого
сохранения из админки. ``get_*`` всегда возвращает полный объект (дефолт,
перекрытый сохранёнными полями).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from core.repositories.app_setting import AppSettingRepository

ABOUT_KEY = "about"
SUPPORT_KEY = "support"
ACTIVITY_KEY = "activity"
PLANS_KEY = "plans"

DEFAULT_ABOUT: dict[str, str] = {
    "app_name": "CAT",
    "version": "0.1.0",
    "body": (
        "Панель управления Telegram-аккаунтами: прогрев, пул и модуль "
        "комментирования. Работает как Telegram Mini App."
    ),
}

DEFAULT_SUPPORT: dict[str, object] = {
    # @username менеджера (без @) для ссылки «написать в ЛС».
    "manager_username": "",
    # Произвольная ссылка на ЛС/чат менеджера (если задана — приоритетнее username).
    "manager_url": "",
    # Включён ли чат поддержки внутри приложения (ветка «остаться в приложении»).
    "in_app_enabled": True,
    # Приветственный текст над формой обращения.
    "intro": "Опишите проблему — менеджер ответит здесь же, в приложении.",
}


DEFAULT_ACTIVITY: dict[str, str] = {
    # IANA-таймзона, в которой считается окно активности и показываются времена.
    "timezone": "UTC",
    # Окно активности по умолчанию (HH:MM) — используется прогревом как фолбэк,
    # когда у персоны не задано своё окно.
    "window_start": "09:00",
    "window_end": "23:00",
}


# Редактируемая из админки «витрина» тарифов (tagline + буллеты). Сами лимиты
# остаются в коде (core.billing.plans) — здесь только текст для экрана тарифов.
DEFAULT_PLANS: dict[str, dict] = {
    "free": {
        "tagline": "Попробовать без оплаты",
        "bullets": [
            "1 аккаунт, 1 персона",
            "1 активная кампания",
            "До 20 комментариев в сутки",
            "История активности — 3 дня",
            "Комьюнити-поддержка",
        ],
    },
    "pro": {
        "tagline": "Весь функционал без ограничений",
        "bullets": [
            "Безлимит аккаунтов, персон и прокси",
            "Безлимит активных кампаний",
            "До 3000 комментариев в сутки",
            "Свой ключ модели, приоритет в очереди",
            "История активности — 365 дней",
            "Приоритетная поддержка",
        ],
    },
}


def _merged(defaults: dict, stored: Optional[dict]) -> dict:
    result = dict(defaults)
    if stored:
        for k in defaults:
            if k in stored and stored[k] is not None:
                result[k] = stored[k]
    return result


def get_about(session: Session) -> dict:
    return _merged(DEFAULT_ABOUT, AppSettingRepository(session).get(ABOUT_KEY))


def set_about(
    session: Session, data: dict, *, updated_by: Optional[str] = None
) -> dict:
    merged = _merged(DEFAULT_ABOUT, data)
    AppSettingRepository(session).set(ABOUT_KEY, merged, updated_by=updated_by)
    return merged


def get_activity(session: Session) -> dict:
    return _merged(DEFAULT_ACTIVITY, AppSettingRepository(session).get(ACTIVITY_KEY))


def set_activity(
    session: Session, data: dict, *, updated_by: Optional[str] = None
) -> dict:
    merged = _merged(DEFAULT_ACTIVITY, data)
    AppSettingRepository(session).set(ACTIVITY_KEY, merged, updated_by=updated_by)
    return merged


def get_plans(session: Session) -> dict:
    return _merged(DEFAULT_PLANS, AppSettingRepository(session).get(PLANS_KEY))


def set_plans(
    session: Session, data: dict, *, updated_by: Optional[str] = None
) -> dict:
    merged = _merged(DEFAULT_PLANS, data)
    AppSettingRepository(session).set(PLANS_KEY, merged, updated_by=updated_by)
    return merged


def get_support(session: Session) -> dict:
    return _merged(DEFAULT_SUPPORT, AppSettingRepository(session).get(SUPPORT_KEY))


def set_support(
    session: Session, data: dict, *, updated_by: Optional[str] = None
) -> dict:
    merged = _merged(DEFAULT_SUPPORT, data)
    AppSettingRepository(session).set(SUPPORT_KEY, merged, updated_by=updated_by)
    return merged
