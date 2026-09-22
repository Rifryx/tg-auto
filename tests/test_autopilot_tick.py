"""Интеграционный тест autopilot_tick_impl (этап 12).

БД настоящая (нужны реальные ФК/CHECK'и); Redis/очередь — spy.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text

from core.config import get_settings
from core.enums import AutopilotActionStatus, AutopilotActionType, GoalType
from core.models import Account, AutopilotAction, AutopilotGoal, BanRiskSnapshot
from core.queue.task_names import TaskName
from worker.tasks.autopilot import autopilot_tick_impl

pytestmark = pytest.mark.asyncio

_TABLES = (
    "autopilot_actions",
    "autopilot_goals",
    "ban_risk_snapshots",
    "accounts",
    "account_status_history",
    "warming_activities",
    "health_events",
    "account_health",
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Ctx:
    def __init__(self, session):
        self._s = session

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


class _SpyPublisher:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, channel, payload):
        self.events.append((channel, dict(payload)))


class _SpyQueue:
    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue(self, task_name, *args, **kwargs):
        self.enqueued.append((task_name, args, kwargs))
        return "job-1"


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _make_account(session, phone, status="created", warming_profile="medium"):
    acc = Account(
        phone=phone,
        session_enc=b"enc",
        status=status,
        warming_profile=warming_profile,
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc.id


def _ctx(session, *, publisher=None, task_queue=None):
    return {
        "session_factory": lambda: _Ctx(session),
        "publisher": publisher,
        "task_queue": task_queue,
    }


async def test_tick_no_goals_is_noop(session):
    _clean(session)
    result = await autopilot_tick_impl(_ctx(session))
    assert result == {"planned": 0, "executed": 0}


async def test_tick_maintain_pool_starts_warming(session):
    """Цель: держать 2 в pool. Есть 2 created — стартуем прогрев обоих."""
    _clean(session)
    a1 = _make_account(session, "+100000000001", status="created")
    a2 = _make_account(session, "+100000000002", status="created")

    session.add(AutopilotGoal(
        user_id="u1",
        goal_type=GoalType.MAINTAIN_POOL_SIZE.value,
        params={"target": 2},
    ))
    session.commit()

    pub = _SpyPublisher()
    q = _SpyQueue()
    result = await autopilot_tick_impl(_ctx(session, publisher=pub, task_queue=q))

    assert result["planned"] == 2
    assert result["executed"] == 2

    # Оба аккаунта переведены в warming через state machine.
    session.expire_all()
    for aid in (a1, a2):
        acc = session.get(Account, aid)
        assert acc.status == "warming"

    # Задачи прогрева поставлены в очередь.
    enqueued_names = [name for name, _args, _ in q.enqueued]
    assert enqueued_names.count(TaskName.WARMING_INITIAL_START) == 2

    # Журнал автопилота: два executed действия start_warming.
    actions = session.execute(select(AutopilotAction)).scalars().all()
    assert len(actions) == 2
    assert all(a.action_type == AutopilotActionType.START_WARMING.value for a in actions)
    assert all(a.status == AutopilotActionStatus.EXECUTED.value for a in actions)

    # Публикация в pub/sub.
    assert any(ch == "autopilot.events" for ch, _ in pub.events)


async def test_tick_retire_risky_account(session):
    """Аккаунт с ban_risk=0.9 → retire через цель keep_low_risk."""
    _clean(session)
    aid = _make_account(session, "+100000000010", status="pool")
    session.add(BanRiskSnapshot(account_id=aid, risk_score=0.9, risk_level="critical"))
    session.add(AutopilotGoal(
        user_id="u1",
        goal_type=GoalType.KEEP_LOW_RISK.value,
        params={"max_risk": 0.3},
    ))
    session.commit()

    result = await autopilot_tick_impl(_ctx(session, task_queue=_SpyQueue()))
    assert result["executed"] == 1

    session.expire_all()
    assert session.get(Account, aid).status == "retired"

    action = session.execute(select(AutopilotAction)).scalar_one()
    assert action.action_type == AutopilotActionType.RETIRE_RISKY.value
    assert action.status == AutopilotActionStatus.EXECUTED.value


async def test_tick_throttles_warming_profile(session):
    """ban_risk=0.65 → throttle (warming_profile → minimal)."""
    _clean(session)
    aid = _make_account(session, "+100000000020", status="pool", warming_profile="dense")
    session.add(BanRiskSnapshot(account_id=aid, risk_score=0.65, risk_level="high"))
    session.add(AutopilotGoal(
        user_id="u1",
        goal_type=GoalType.KEEP_LOW_RISK.value,
        params={"max_risk": 0.3},
    ))
    session.commit()

    await autopilot_tick_impl(_ctx(session, task_queue=_SpyQueue()))

    session.expire_all()
    acc = session.get(Account, aid)
    assert acc.warming_profile == "minimal"
    assert acc.status == "pool"  # не retire — просто снизили профиль

    action = session.execute(select(AutopilotAction)).scalar_one()
    assert action.action_type == AutopilotActionType.THROTTLE.value
    assert action.status == AutopilotActionStatus.EXECUTED.value


async def test_disabled_goal_ignored(session):
    """enabled=false → цель не участвует в планировании."""
    _clean(session)
    _make_account(session, "+100000000030", status="created")
    session.add(AutopilotGoal(
        user_id="u1",
        goal_type=GoalType.MAINTAIN_POOL_SIZE.value,
        params={"target": 5},
        enabled=False,
    ))
    session.commit()

    result = await autopilot_tick_impl(_ctx(session))
    assert result == {"planned": 0, "executed": 0}
