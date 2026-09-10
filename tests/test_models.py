from __future__ import annotations

from datetime import time

import pytest

from core.models import (
    Account,
    AccountStatusHistory,
    Campaign,
    CampaignAccount,
    CommentLog,
    HealthEvent,
    Persona,
    Proxy,
    WarmingActivity,
)


def _make_account(**overrides) -> Account:
    defaults = dict(
        phone="+10000000001",
        session_enc=b"encrypted-session",
        device_model="Samsung SM-S928B",
        system_version="SDK 34",
        app_version="10.14.5 (5218)",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    defaults.update(overrides)
    return Account(**defaults)


def test_proxy_roundtrip(session):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5", geo="UA")
    session.add(p)
    session.flush()
    assert p.id is not None
    assert p.status == "unchecked"


def test_persona_roundtrip(session):
    persona = Persona(name="Anna", personality_tags=["curious", "friendly"])
    session.add(persona)
    session.flush()
    assert persona.id is not None
    assert persona.personality_tags == ["curious", "friendly"]


def test_account_roundtrip(session):
    proxy = Proxy(host="1.2.3.4", port=1080, type="socks5")
    persona = Persona(name="Ivan", personality_tags=[])
    session.add_all([proxy, persona])
    session.flush()

    acc = _make_account(proxy_id=proxy.id, persona_id=persona.id)
    session.add(acc)
    session.flush()
    assert acc.id is not None
    assert acc.status == "created"
    assert acc.warming_profile == "medium"


def test_warming_activity(session):
    acc = _make_account(phone="+10000000002")
    session.add(acc)
    session.flush()

    w = WarmingActivity(
        account_id=acc.id,
        kind="initial",
        action_type="subscribe_channel",
        target="@durov",
        status="done",
        meta={"channel_id": 123},
    )
    session.add(w)
    session.flush()
    assert w.id is not None


def test_health_event(session):
    acc = _make_account(phone="+10000000003")
    session.add(acc)
    session.flush()

    ev = HealthEvent(
        account_id=acc.id,
        event_type="flood_wait",
        meta={"seconds": 42},
    )
    session.add(ev)
    session.flush()
    assert ev.id is not None
    assert ev.resolved is False


def test_account_status_history(session):
    acc = _make_account(phone="+10000000004")
    session.add(acc)
    session.flush()

    h = AccountStatusHistory(
        account_id=acc.id,
        from_status=None,
        to_status="created",
        reason="account.created",
        initiator="user",
    )
    session.add(h)
    session.flush()
    assert h.id is not None


def _make_campaign(**overrides) -> Campaign:
    defaults = dict(
        name="daily",
        target_channel="@my_channel",
        base_system_prompt="be nice",
        llm_provider="deepseek",
        active_hours_start=time(9, 0),
        active_hours_end=time(23, 0),
        active_hours_tz="Europe/Kiev",
        posting_delay_min_sec=30,
        posting_delay_max_sec=180,
    )
    defaults.update(overrides)
    return Campaign(**defaults)


def test_campaign_roundtrip(session):
    c = _make_campaign()
    session.add(c)
    session.flush()
    assert c.id is not None
    assert c.enabled is True


def test_campaign_account_link(session):
    acc = _make_account(phone="+10000000005")
    campaign = _make_campaign(name="link")
    session.add_all([acc, campaign])
    session.flush()

    link = CampaignAccount(campaign_id=campaign.id, account_id=acc.id)
    session.add(link)
    session.flush()

    fetched = session.get(CampaignAccount, {"campaign_id": campaign.id, "account_id": acc.id})
    assert fetched is not None


def test_comment_log(session):
    acc = _make_account(phone="+10000000006")
    campaign = _make_campaign(name="log")
    session.add_all([acc, campaign])
    session.flush()

    log = CommentLog(
        campaign_id=campaign.id,
        account_id=acc.id,
        post_channel_msg_id=555,
        comment_text="+1",
        status="posted",
    )
    session.add(log)
    session.flush()
    assert log.id is not None


def test_account_check_constraints(session):
    # Плохой status → нарушение CHECK
    from sqlalchemy.exc import IntegrityError

    acc = _make_account(phone="+10000000007", status="not_a_real_status")
    session.add(acc)
    with pytest.raises(IntegrityError):
        session.flush()


def test_account_assignment_pair_consistency(session):
    from sqlalchemy.exc import IntegrityError

    acc = _make_account(
        phone="+10000000008",
        assigned_container_type="commenting",
        assigned_container_id=None,
    )
    session.add(acc)
    with pytest.raises(IntegrityError):
        session.flush()


def test_campaign_account_unique_account_id(session):
    from sqlalchemy.exc import IntegrityError

    acc = _make_account(phone="+10000000009")
    c1 = _make_campaign(name="c1")
    c2 = _make_campaign(name="c2")
    session.add_all([acc, c1, c2])
    session.flush()

    session.add(CampaignAccount(campaign_id=c1.id, account_id=acc.id))
    session.flush()
    session.add(CampaignAccount(campaign_id=c2.id, account_id=acc.id))
    with pytest.raises(IntegrityError):
        session.flush()
