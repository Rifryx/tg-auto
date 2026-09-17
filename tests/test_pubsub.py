"""Юнит-тесты pub/sub-обвязки (аудит #9), без Redis/БД.

Проверяем: реальный публикатор из get_publisher; диспетчеризацию каналов в
EventHub (login-кэш обновляется только login-каналом, SSE получает оба типа);
health-алерты (severity + payload).
"""

from __future__ import annotations

import json

import pytest

from core.enums import HealthEventType
from core.queue.publisher import Publisher, RedisPublisher

pytestmark = pytest.mark.filterwarnings("ignore")


class _SpyRedis:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    def publish(self, channel, data):
        self.published.append((channel, data))


# --- 1. get_publisher реальный (не None) -------------------------------------


def test_get_publisher_is_real(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", "k")
    from core.config import get_settings

    get_settings.cache_clear()
    import api.deps.queue as q

    q._publisher.cache_clear()
    pub = q.get_publisher()
    assert pub is not None
    assert isinstance(pub, Publisher)
    get_settings.cache_clear()


def test_redis_publisher_serializes_json():
    spy = _SpyRedis()
    RedisPublisher(spy).publish("account_status", {"account_id": 5, "to": "banned"})
    assert len(spy.published) == 1
    channel, data = spy.published[0]
    assert channel == "account_status"
    assert json.loads(data) == {"account_id": 5, "to": "banned"}


# --- 2. EventHub диспетчеризует login и account_status -----------------------


@pytest.mark.asyncio
async def test_hub_dispatches_both_channels_login_cache_only_login():
    from api.services.login import LOGIN_CHANNEL, LoginEventHub
    from core.state_machine.account import ACCOUNT_STATUS_CHANNEL

    hub = LoginEventHub("redis://x")
    queue = hub.subscribe(7)

    hub._handle(LOGIN_CHANNEL, {"account_id": 7, "state": "waiting_code"})
    hub._handle(
        ACCOUNT_STATUS_CHANNEL,
        {"account_id": 7, "from": "pool", "to": "banned", "reason": "health.ban_detected", "initiator": "health"},
    )

    e1 = await queue.get()
    e2 = await queue.get()
    assert e1["type"] == "login" and e1["state"] == "waiting_code"
    assert e2["type"] == "account_status" and e2["to"] == "banned"

    # login-кэш (GET /login/state) хранит только login-состояние
    cached = hub.get_state(7)
    assert cached["type"] == "login" and cached["state"] == "waiting_code"


@pytest.mark.asyncio
async def test_hub_ignores_payload_without_account_id():
    from api.services.login import LOGIN_CHANNEL, LoginEventHub

    hub = LoginEventHub("redis://x")
    queue = hub.subscribe(1)
    hub._handle(LOGIN_CHANNEL, {"state": "x"})  # нет account_id
    assert queue.empty()


# --- 2b. MonitoringEventHub: глобальный fan-out доменных событий (#9) ---------


@pytest.mark.asyncio
async def test_monitoring_hub_fanout_all_channels():
    from api.services.events import MonitoringEventHub

    hub = MonitoringEventHub("redis://x")
    q1 = hub.subscribe()
    q2 = hub.subscribe()

    hub._fanout("health_alert", {"account_id": 5, "event_type": "spam_block", "severity": "critical"})
    hub._fanout("account_status", {"account_id": 5, "to": "banned"})

    # оба подписчика получают КАЖДОЕ событие (глобальный fan-out)
    for q in (q1, q2):
        a = await q.get()
        b = await q.get()
        assert a["type"] == "health_alert" and a["severity"] == "critical"
        assert b["type"] == "account_status" and b["to"] == "banned"

    hub.unsubscribe(q2)
    hub._fanout("warming_progress", {"account_id": 5, "status": "done"})
    assert (await q1.get())["type"] == "warming_progress"
    assert q2.empty()  # отписанный больше не получает


# --- 3. health-алерты: severity + payload ------------------------------------


def test_health_severity_mapping():
    from worker.health.monitor import _severity

    assert _severity(HealthEventType.FLOOD_WAIT) == "warning"
    assert _severity(HealthEventType.PROXY_DOWN) == "warning"
    assert _severity(HealthEventType.SPAM_BLOCK) == "critical"
    assert _severity(HealthEventType.SESSION_REVOKED) == "critical"


def test_publish_alert_payload():
    from worker.health.monitor import HEALTH_ALERT_CHANNEL, _publish_alert

    spy = _SpyRedis()
    _publish_alert(RedisPublisher(spy), account_id=9, event_type=HealthEventType.SPAM_BLOCK)

    assert len(spy.published) == 1
    channel, data = spy.published[0]
    assert channel == HEALTH_ALERT_CHANNEL
    assert json.loads(data) == {
        "account_id": 9,
        "event_type": "spam_block",
        "severity": "critical",
    }


def test_publish_alert_noop_without_publisher():
    from worker.health.monitor import _publish_alert

    # None-публикатор не роняет вызов (аудит #9: fail-open)
    _publish_alert(None, account_id=1, event_type=HealthEventType.FLOOD_WAIT)
