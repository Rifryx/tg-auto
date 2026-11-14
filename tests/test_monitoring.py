"""Тесты дашборда мониторинга (PROJECT-STAGES §10).

БД настоящая (тестовый Postgres). Так как другие тесты коммитят строки в общую
БД, каждый тест начинает с TRUNCATE релевантных таблиц — для детерминизма.
Кэш — фейковый in-memory (проверяем логику кэширования, не реальный TTL).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from api.deps.auth import require_user
from api.deps.db import get_session
from api.routers import monitoring as monitoring_router
from api.services.monitoring import get_cache_redis
from core.models import (
    Account,
    Campaign,
    CampaignAccount,
    CommentLog,
    HealthEvent,
    MonitoredChannel,
    WarmingActivity,
)

_TABLES = (
    "accounts",
    "proxies",
    "personas",
    "account_status_history",
    "health_events",
    "warming_activities",
    '"commenting".campaigns',
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
    '"commenting".monitored_channels',
)


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value


class _CountingSession:
    """Обёртка над Session, считающая обращения к execute (spy к БД)."""

    def __init__(self, real) -> None:
        self._real = real
        self.execute_count = 0

    def execute(self, *args, **kwargs):
        self.execute_count += 1
        return self._real.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _clean(session) -> None:
    session.execute(
        text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
    )
    session.commit()


def _phone(n: int) -> str:
    return f"+{70_000_000_000 + n}"


def _make_account(session, n: int, status: str = "created") -> Account:
    acc = Account(
        phone=_phone(n),
        # Владелец = пользователь дашборда (_make_app override require_user →
        # "user-1"); иначе multi-tenancy-фильтр дашборда их не покажет.
        user_id="user-1",
        session_enc=b"enc",
        status=status,
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    return acc


def _client(app) -> TestClient:
    return TestClient(app)


def _make_app(session, cache) -> FastAPI:
    app = FastAPI()
    app.include_router(monitoring_router.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_cache_redis] = lambda: cache
    app.dependency_overrides[require_user] = lambda: "user-1"
    return app


# --- 1. Пустая БД -------------------------------------------------------------


def test_dashboard_empty_db(session):
    _clean(session)
    app = _make_app(session, _FakeCache())
    resp = _client(app).get("/monitoring/dashboard")
    assert resp.status_code == 200
    body = resp.json()

    assert body["alerts"] == []
    assert body["accounts_summary"] == {
        "created": 0,
        "warming": 0,
        "pool": 0,
        "assigned": 0,
        "cooldown": 0,
        "retired": 0,
        "banned": 0,
    }
    assert body["modules_summary"] == [
        {"module": "commenting", "instances": 0, "active_now": 0, "today_actions": 0},
        {"module": "shilling", "instances": 0, "active_now": 0, "today_actions": 0},
        {"module": "priming", "instances": 0, "active_now": 0, "today_actions": 0},
        {"module": "mass_reactions", "instances": 0, "active_now": 0, "today_actions": 0},
    ]
    assert body["kpis"] == {
        "actions_today": 0,
        "errors_today": 0,
        "active_campaigns": 0,
        "paused_campaigns": 0,
        "accounts_working": 0,
    }
    # 7-дневный ряд: ровно 7 точек, все нули на пустой БД.
    assert len(body["trend_7d"]) == 7
    assert all(p["actions"] == 0 for p in body["trend_7d"])
    assert [p["date"] for p in body["trend_7d"]] == sorted(p["date"] for p in body["trend_7d"])
    assert body["recent_activity"] == []


# --- 2. Наполненная БД: цифры совпадают с прямыми SQL -------------------------


def test_dashboard_matches_direct_sql(session):
    _clean(session)

    # аккаунты разных стадий
    a_created = _make_account(session, 1, "created")
    a_pool = _make_account(session, 2, "pool")
    a_assigned = _make_account(session, 3, "assigned")
    a_banned = _make_account(session, 4, "banned")

    # health events: 2 unresolved + 1 resolved
    session.add_all(
        [
            HealthEvent(account_id=a_pool.id, event_type="spam_block", resolved=False),
            HealthEvent(account_id=a_assigned.id, event_type="flood_wait", resolved=False),
            HealthEvent(account_id=a_banned.id, event_type="auth_failed", resolved=True),
        ]
    )

    # warming + comment activity
    session.add_all(
        [
            WarmingActivity(
                account_id=a_pool.id, kind="maintenance",
                action_type="read_history", status="done",
                target="durov", meta={"read": 24},
            ),
            WarmingActivity(
                account_id=a_pool.id, kind="initial",
                action_type="subscribe_channel", status="done",
            ),
        ]
    )
    campaign = Campaign(
        name="c1", target_channel="@ch", base_system_prompt="p",
        llm_provider="deepseek", active_hours_start=datetime(2020, 1, 1, 9).time(),
        active_hours_end=datetime(2020, 1, 1, 23).time(), active_hours_tz="UTC",
        posting_delay_min_sec=1, posting_delay_max_sec=5,
    )
    session.add(campaign)
    session.flush()
    session.add_all(
        [
            CampaignAccount(campaign_id=campaign.id, account_id=a_assigned.id),
            CampaignAccount(campaign_id=campaign.id, account_id=a_pool.id),
        ]
    )
    session.add(
        CommentLog(
            campaign_id=campaign.id, account_id=a_assigned.id,
            post_channel_msg_id=100, comment_text="hi", status="posted",
        )
    )
    session.commit()

    body = _client(_make_app(session, _FakeCache())).get("/monitoring/dashboard").json()

    # accounts_summary vs прямой SQL
    expected_summary = {
        s: c
        for s, c in session.execute(
            select(Account.status, func.count()).group_by(Account.status)
        ).all()
    }
    for status, count in expected_summary.items():
        assert body["accounts_summary"][status] == count
    assert body["accounts_summary"]["created"] == 1
    assert body["accounts_summary"]["banned"] == 1

    # alerts = unresolved
    unresolved = session.execute(
        select(func.count()).select_from(HealthEvent).where(HealthEvent.resolved.is_(False))
    ).scalar_one()
    assert len(body["alerts"]) == unresolved == 2
    severities = {a["severity"] for a in body["alerts"]}
    assert severities == {"critical", "warning"}

    # modules_summary commenting
    module = body["modules_summary"][0]
    assert module["instances"] == session.execute(
        select(func.count()).select_from(CampaignAccount)
    ).scalar_one() == 2
    assert module["active_now"] == 1  # только a_assigned в статусе assigned
    assert module["today_actions"] == 1

    # recent_activity: 2 warming + 1 comment, по убыванию времени
    assert len(body["recent_activity"]) == 3
    types = {item["type"] for item in body["recent_activity"]}
    assert types == {"warming", "comment"}
    # detail/action_type/status доходят до клиента (не отрезаются response_model):
    warming = next(i for i in body["recent_activity"] if i["action_type"] == "read_history")
    assert warming["detail"] == "прочитал 24 сообщ. в @durov"
    assert warming["status"] == "done"
    timestamps = [item["timestamp"] for item in body["recent_activity"]]
    assert timestamps == sorted(timestamps, reverse=True)


# --- 3. Кэш: второй запрос не идёт в БД ---------------------------------------


def test_recent_activity_shows_channel_for_comment(session):
    """Лента «Активность»: у события-коммента видно, в какой канал он ушёл."""
    from api.services.monitoring import _recent_activity

    _clean(session)
    acc = _make_account(session, 10, "assigned")
    session.add(
        MonitoredChannel(
            account_id=acc.id, input_ref="@testbot",
            channel_ref="testbot", title="тест бота", status="working",
        )
    )
    campaign = Campaign(
        name="c1", target_channel="@ch", base_system_prompt="p",
        llm_provider="deepseek", active_hours_start=datetime(2020, 1, 1, 9).time(),
        active_hours_end=datetime(2020, 1, 1, 23).time(), active_hours_tz="UTC",
        posting_delay_min_sec=1, posting_delay_max_sec=5,
    )
    session.add(campaign)
    session.flush()
    session.add(
        CommentLog(
            campaign_id=campaign.id, account_id=acc.id,
            post_channel_msg_id=57, comment_text="hi", status="posted",
        )
    )
    session.commit()

    events = _recent_activity(session)
    comment = next(e for e in events if e["type"] == "comment")
    assert comment["channel"] == "тест бота"
    assert "тест бота" in comment["detail"]


def test_recent_activity_uses_comment_log_channel_ref(session):
    """Канал берётся из CommentLog.channel_ref (реальный канал поста), а не
    из «первого канала аккаунта». Аккаунт мониторит ДВА канала — подпись
    должна быть именно того, куда ушёл коммент."""
    from api.services.monitoring import _recent_activity

    _clean(session)
    acc = _make_account(session, 11, "assigned")
    # Два канала у аккаунта. «Первый по id» — Alliance, но коммент ушёл в тест бота.
    session.add_all([
        MonitoredChannel(
            account_id=acc.id, input_ref="@alliance",
            channel_ref="alliance", title="Alliance Order's", status="working",
        ),
        MonitoredChannel(
            account_id=acc.id, input_ref="@testbot",
            channel_ref="testbot", title="тест бота", status="working",
        ),
    ])
    campaign = Campaign(
        name="c1", target_channel="@ch", base_system_prompt="p",
        llm_provider="deepseek", active_hours_start=datetime(2020, 1, 1, 9).time(),
        active_hours_end=datetime(2020, 1, 1, 23).time(), active_hours_tz="UTC",
        posting_delay_min_sec=1, posting_delay_max_sec=5,
    )
    session.add(campaign)
    session.flush()
    session.add(
        CommentLog(
            campaign_id=campaign.id, account_id=acc.id,
            post_channel_msg_id=77, comment_text="hi", status="posted",
            channel_ref="тест бота",
        )
    )
    session.commit()

    events = _recent_activity(session)
    comment = next(e for e in events if e["type"] == "comment")
    assert comment["channel"] == "тест бота"
    assert "Alliance" not in (comment["detail"] or "")


def test_recent_activity_no_channel_when_ambiguous_legacy(session):
    """Старый лог без channel_ref и аккаунт с НЕСКОЛЬКИМИ каналами → канал не
    угадываем (лучше без подписи, чем неверная)."""
    from api.services.monitoring import _recent_activity

    _clean(session)
    acc = _make_account(session, 12, "assigned")
    session.add_all([
        MonitoredChannel(
            account_id=acc.id, input_ref="@a", channel_ref="a",
            title="A", status="working",
        ),
        MonitoredChannel(
            account_id=acc.id, input_ref="@b", channel_ref="b",
            title="B", status="working",
        ),
    ])
    campaign = Campaign(
        name="c1", target_channel="@ch", base_system_prompt="p",
        llm_provider="deepseek", active_hours_start=datetime(2020, 1, 1, 9).time(),
        active_hours_end=datetime(2020, 1, 1, 23).time(), active_hours_tz="UTC",
        posting_delay_min_sec=1, posting_delay_max_sec=5,
    )
    session.add(campaign)
    session.flush()
    session.add(
        CommentLog(
            campaign_id=campaign.id, account_id=acc.id,
            post_channel_msg_id=5, comment_text="hi", status="posted",
        )
    )
    session.commit()

    events = _recent_activity(session)
    comment = next(e for e in events if e["type"] == "comment")
    assert comment["channel"] is None


def test_dashboard_cached_second_call_skips_db(session):
    _clean(session)
    counting = _CountingSession(session)
    cache = _FakeCache()
    app = _make_app(counting, cache)
    client = _client(app)

    first = client.get("/monitoring/dashboard")
    assert first.status_code == 200
    assert counting.execute_count > 0
    after_first = counting.execute_count

    second = client.get("/monitoring/dashboard")
    assert second.status_code == 200
    assert second.json() == first.json()
    # второй запрос обслужен из кэша — обращений к БД не прибавилось
    assert counting.execute_count == after_first
