"""Тесты пула прокси и автопика (этап 3, backlog #1 и #2)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.models import Account, Proxy
from core.repositories.proxy_pool import (
    detect_geo,
    pick_for_phone,
    pick_free_proxy,
)


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
            "bulk_job_items, bulk_jobs, accounts, projects, proxies "
            "RESTART IDENTITY CASCADE"
        )
    )
    session.commit()


def _make_proxy(session, *, host="1.1.1.1", geo="UA", status="alive"):
    p = Proxy(host=host, port=1080, type="socks5", geo=geo, status=status)
    session.add(p)
    session.flush()
    session.commit()
    return p


def _make_account(session, phone="+380000", proxy_id=None):
    a = Account(
        phone=phone, session_enc=b"e", status="pool",
        proxy_id=proxy_id,
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    session.flush()
    session.commit()
    return a


# ── detect_geo ──────────────────────────────────────────────────────────────


def test_detect_geo_common_prefixes():
    assert detect_geo("+380 44 111 22 33") == "UA"
    assert detect_geo("380441112233") == "UA"
    assert detect_geo("+79990000001") == "RU"
    assert detect_geo("+49-30-1234567") == "DE"
    assert detect_geo("+1 202 456 1111") == "US"
    assert detect_geo("+8613800138000") == "CN"
    assert detect_geo("+61 2 9374 4000") == "AU"


def test_detect_geo_unknown_returns_none():
    # Несуществующий/редкий префикс → None
    assert detect_geo("+59999999999") is None
    assert detect_geo("+") is None
    assert detect_geo("") is None


def test_detect_geo_prefix_priority():
    """+380 не должен матчиться на +3 или +38."""
    assert detect_geo("+380") == "UA"
    # +49 обгоняет более короткие возможные префиксы:
    assert detect_geo("+491234") == "DE"


# ── pick_free_proxy ────────────────────────────────────────────────────────


def test_pick_free_proxy_returns_none_when_pool_empty(session):
    _clean(session)
    assert pick_free_proxy(session) is None


def test_pick_free_proxy_by_geo(session):
    _clean(session)
    _make_proxy(session, host="ru", geo="RU")
    de = _make_proxy(session, host="de", geo="DE")

    got = pick_free_proxy(session, geo="DE")
    assert got is not None and got.id == de.id


def test_pick_free_proxy_strict_geo_returns_none_when_no_match(session):
    _clean(session)
    _make_proxy(session, host="ua", geo="UA")

    # DE-прокси нет — strict_geo=True (default) → None (не берём другой):
    assert pick_free_proxy(session, geo="DE") is None


def test_pick_free_proxy_non_strict_falls_back(session):
    _clean(session)
    ua = _make_proxy(session, host="ua", geo="UA")

    # DE-прокси нет + strict_geo=False → берём любой alive свободный:
    got = pick_free_proxy(session, geo="DE", strict_geo=False)
    assert got is not None and got.id == ua.id


def test_pick_free_proxy_excludes_occupied(session):
    _clean(session)
    p = _make_proxy(session, geo="UA")
    _make_account(session, proxy_id=p.id)

    assert pick_free_proxy(session, geo="UA") is None


def test_pick_free_proxy_excludes_dead_and_unchecked(session):
    _clean(session)
    _make_proxy(session, host="dead", geo="UA", status="dead")
    _make_proxy(session, host="unchecked", geo="UA", status="unchecked")
    assert pick_free_proxy(session, geo="UA") is None

    alive = _make_proxy(session, host="alive", geo="UA", status="alive")
    got = pick_free_proxy(session, geo="UA")
    assert got is not None and got.id == alive.id


# ── pick_for_phone ────────────────────────────────────────────────────────


def test_pick_for_phone_auto_detects_geo(session):
    _clean(session)
    ua = _make_proxy(session, host="ua", geo="UA")
    _make_proxy(session, host="ru", geo="RU")

    got = pick_for_phone(session, "+380441112233")
    assert got is not None and got.id == ua.id


def test_pick_for_phone_unknown_number_gets_no_proxy_by_default(session):
    """detect_geo=None → geo=None → любой alive свободный (не strict)."""
    _clean(session)
    ua = _make_proxy(session, host="ua", geo="UA")

    got = pick_for_phone(session, "+59900000000")
    # detect_geo=None → strict_geo применяется только если geo задан → берём любой.
    assert got is not None and got.id == ua.id


def test_pick_for_phone_strict_no_matching(session):
    _clean(session)
    _make_proxy(session, host="ua", geo="UA")

    # RU-номер, RU-прокси нет, strict → None:
    got = pick_for_phone(session, "+79990000001")
    assert got is None
