"""Тесты нормализации номера и pre-check занятости (bot-ui-logic-fixes).

Покрывает:
* ``normalize_phone`` — единый вид номера (ведущий «+», без пробелов/скобок);
* ``phone_exists`` — учитывает нормализацию (разный формат → тот же аккаунт);
* создание аккаунта хранит номер в нормализованном виде и ловит дубликат;
* удаление аккаунта освобождает номер (повторное добавление снова возможно).
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from api.services import accounts as accounts_service
from core.config import get_settings
from core.enums import WarmingProfile
from core.models import Proxy


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _clean(session):
    session.execute(
        text(
            "TRUNCATE autopilot_actions, autopilot_goals, project_channels, "
            "bulk_job_items, bulk_jobs, account_status_history, accounts, "
            "projects, proxies RESTART IDENTITY CASCADE"
        )
    )
    session.commit()


def _make_proxy(session):
    p = Proxy(host="1.1.1.1", port=1080, type="socks5", geo="UA", status="alive")
    session.add(p)
    session.flush()
    session.commit()
    return p


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+380123456789", "+380123456789"),
        ("380123456789", "+380123456789"),
        (" 380 12 345 67 89 ", "+380123456789"),
        ("+38 (012) 345-67-89", "+380123456789"),
        ("", ""),
        ("  ", ""),
    ],
)
def test_normalize_phone(raw, expected):
    assert accounts_service.normalize_phone(raw) == expected


def test_create_normalizes_and_detects_duplicate(session):
    _clean(session)
    proxy = _make_proxy(session)

    acc = accounts_service.create_account(
        session,
        phone="380123456789",
        proxy_id=proxy.id,
        persona_id=None,
        warming_profile=WarmingProfile.MEDIUM,
    )
    # Сохранён в нормализованном виде (с «+»).
    assert acc.phone == "+380123456789"

    # Тот же номер в другом формате — считается занятым до создания.
    assert accounts_service.phone_exists(session, "+38 (012) 345-67-89") is True

    with pytest.raises(accounts_service.PhoneAlreadyExistsError):
        accounts_service.create_account(
            session,
            phone="+380123456789",
            proxy_id=proxy.id,
            persona_id=None,
            warming_profile=WarmingProfile.MEDIUM,
        )


def test_delete_frees_phone_for_reuse(session):
    _clean(session)
    proxy = _make_proxy(session)

    acc = accounts_service.create_account(
        session,
        phone="+380111111111",
        proxy_id=proxy.id,
        persona_id=None,
        warming_profile=WarmingProfile.MEDIUM,
    )
    assert accounts_service.phone_exists(session, "+380111111111") is True

    assert accounts_service.delete_account(session, acc.id) is True

    # После удаления номер свободен — «пустышка» не оседает и не блокирует.
    assert accounts_service.phone_exists(session, "+380111111111") is False
    reused = accounts_service.create_account(
        session,
        phone="+380111111111",
        proxy_id=proxy.id,
        persona_id=None,
        warming_profile=WarmingProfile.MEDIUM,
    )
    assert reused.id != acc.id


def test_phone_exists_false_for_blank(session):
    _clean(session)
    assert accounts_service.phone_exists(session, "") is False
    assert accounts_service.phone_exists(session, "   ") is False
