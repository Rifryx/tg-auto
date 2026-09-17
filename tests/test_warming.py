"""Тесты движка прогрева (PROJECT-STAGES §3).

БД настоящая; клиент Telethon и ClientPool — фейковые (никаких сетевых
вызовов), время и RNG инъектируются через ctx (fake clock / seeded RNG).
Таблицы очищаются в начале каждого теста для детерминизма.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select, text

from core.config import get_settings

from core.crypto import reset_cache
from core.enums import WarmingActionType, WarmingProfile
from core.models import Account, HealthEvent, WarmingActivity
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from worker.tasks.warming import (
    WARMING_PROGRESS_CHANNEL,
    initial_start_impl,
    maintenance_scheduler_impl,
    warming_tick_impl,
)
# worker.login импортируется ПОСЛЕ worker.tasks: flow.py тянет
# worker.tasks.dispatch, поэтому пакет worker.tasks должен инициализироваться
# первым (иначе циклический импорт handlers ↔ login).
from worker.login import login_confirm_impl

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch):
    # planner.is_within_active_window читает окна из core.config.
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

# В окне 09:00–23:00 Europe/Kiev: 10:00 UTC → 13:00 Kiev (внутри).
NOW_INSIDE = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
# 00:30 UTC → 03:30 Kiev (вне окна).
NOW_OUTSIDE = datetime(2026, 9, 12, 0, 30, tzinfo=timezone.utc)

_TABLES = (
    "accounts",
    "warming_activities",
    "health_events",
    "account_status_history",
    "ban_risk_snapshots",
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)
_PHONE = iter(range(80_000_000_000, 80_001_000_000))


class _Ctx:
    def __init__(self, session):
        self._s = session

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.gets = 0
        self.releases = 0

    async def get(self, account_id):
        self.gets += 1
        return self._client

    async def release(self, account_id):
        self.releases += 1


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue(self, task_name, *args, **kwargs):
        self.enqueued.append((task_name, args))
        return "job-1"


class _FixedRng:
    def __init__(self, action: WarmingActionType):
        self._action = action

    def choice(self, seq):
        return self._action

    def choices(self, population, *, weights=None, k=1):
        return [self._action] * k

    def randint(self, a, b):
        return a

    def uniform(self, a, b):
        return a


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _make_account(session, *, status, profile=WarmingProfile.MEDIUM, warming_started_at=None):
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status=status,
        warming_profile=profile.value,
        warming_started_at=warming_started_at,
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


def _ctx(session, *, now, rng=None, client=None, task_queue=None, governor=None, publisher=None):
    return {
        "session_factory": lambda: _Ctx(session),
        "now": now,
        "rng": rng,
        "client_pool": _FakePool(client) if client is not None else None,
        "task_queue": task_queue,
        "governor": governor,
        "publisher": publisher,
    }


class _Req:
    pass


class _SpyPublisher:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, channel, payload):
        self.events.append((channel, dict(payload)))


class _DenyGovernor:
    async def check_and_reserve(self, account_id, action_type):
        return False


def _activity_count(session, account_id, **filters) -> int:
    stmt = select(func.count()).select_from(WarmingActivity).where(
        WarmingActivity.account_id == account_id
    )
    for col, val in filters.items():
        stmt = stmt.where(getattr(WarmingActivity, col) == val)
    return session.execute(stmt).scalar_one()


# --- 1. created → warming → 50 initial-действий → pool ------------------------


async def test_initial_warming_completes_to_pool(session):
    _clean(session)
    account_id = _make_account(
        session, status="warming", warming_started_at=NOW_INSIDE
    )
    client = AsyncMock()  # любые вызовы клиента успешны
    spy = _SpyTaskQueue()
    ctx = _ctx(
        session,
        now=NOW_INSIDE,
        rng=_FixedRng(WarmingActionType.IDLE_ONLINE),
        client=client,
        task_queue=spy,
    )

    # initial_start планирует стартовую пачку tick'ов (medium: 2..5, rng→low=2)
    scheduled = await initial_start_impl(ctx, account_id)
    assert scheduled == 2
    assert all(name == "warming.tick" or name.value == "warming.tick" for name, _ in spy.enqueued)

    # ускоренная серия tick'ов
    for _ in range(50):
        await warming_tick_impl(ctx, account_id)

    assert AccountRepository(session).get(account_id).status == "pool"
    # все 50 действий записаны как initial
    assert _activity_count(session, account_id, kind="initial") == 50
    assert _activity_count(session, account_id, kind="maintenance") == 0


# --- 2. maintenance_scheduler: интервалы по пресетам --------------------------


async def test_maintenance_scheduler_enqueues_due_by_preset(session):
    _clean(session)
    now = NOW_INSIDE

    # (profile, часы с последней активности, ожидается ли enqueue)
    cases = {
        (WarmingProfile.MINIMAL, 60): True,   # >48ч → пора
        (WarmingProfile.MINIMAL, 30): False,  # <48ч
        (WarmingProfile.MEDIUM, 25): True,    # >20ч
        (WarmingProfile.MEDIUM, 10): False,   # <20ч
        (WarmingProfile.DENSE, 7): True,      # >6ч
        (WarmingProfile.DENSE, 3): False,     # <6ч
    }
    expected_due = set()
    for (profile, hours_ago), due in cases.items():
        aid = _make_account(session, status="pool", profile=profile)
        session.add(
            WarmingActivity(
                account_id=aid, kind="maintenance", action_type="idle_online",
                status="done", created_at=now - timedelta(hours=hours_ago),
            )
        )
        if due:
            expected_due.add(aid)
    session.commit()

    spy = _SpyTaskQueue()
    ctx = _ctx(session, now=now, task_queue=spy)
    result = await maintenance_scheduler_impl(ctx)

    enqueued_ids = {args[0] for _, args in spy.enqueued}
    assert enqueued_ids == expected_due
    assert set(result) == expected_due


# --- 3. tick вне окна активности пропускается --------------------------------


async def test_tick_outside_active_window_skipped(session):
    _clean(session)
    account_id = _make_account(
        session, status="warming", warming_started_at=NOW_OUTSIDE
    )
    client = AsyncMock()
    ctx = _ctx(
        session,
        now=NOW_OUTSIDE,
        rng=_FixedRng(WarmingActionType.IDLE_ONLINE),
        client=client,
    )

    result = await warming_tick_impl(ctx, account_id)

    assert result == "skipped"
    assert _activity_count(session, account_id) == 0
    assert ctx["client_pool"].gets == 0  # клиент даже не запрашивался


# --- 4. reaction на несуществующий пост → failed, аккаунт продолжает работать -


async def test_reaction_on_missing_post_records_failed(session):
    _clean(session)
    account_id = _make_account(
        session, status="warming", warming_started_at=NOW_INSIDE
    )
    client = AsyncMock()
    client.get_messages = AsyncMock(return_value=[])  # «поста нет»
    ctx = _ctx(
        session,
        now=NOW_INSIDE,
        rng=_FixedRng(WarmingActionType.REACTION),
        client=client,
    )

    result = await warming_tick_impl(ctx, account_id)

    assert result == "failed"
    assert _activity_count(session, account_id, status="failed", action_type="reaction") == 1
    # аккаунт не сломался: остаётся в warming, следующий (успешный) tick работает
    assert AccountRepository(session).get(account_id).status == "warming"

    client.get_messages = AsyncMock(return_value=[type("M", (), {"id": 1})()])
    ctx["rng"] = _FixedRng(WarmingActionType.IDLE_ONLINE)
    assert await warming_tick_impl(ctx, account_id) == "done"


# --- 5. e2e: login_confirm → warming → (ускоренный прогон) → pool -------------


async def test_login_confirm_to_pool_without_manual_initial_start(session):
    """created→warming→pool целиком от login_confirm, БЕЗ ручного initial_start.

    Регрессия на #1/#2/#11: раньше путь заводился только ручным вызовом
    initial_start_impl в тесте. Теперь login_confirm сам ставит прогрев в
    очередь (проверяем spy), а аккаунт доходит до pool на ускоренной серии
    tick'ов.
    """
    reset_cache()
    _clean(session)

    # Аккаунт в 'created' с pending-логином (phone_code_hash в meta).
    account_id = _make_account(session, status="created", warming_started_at=None)
    account = AccountRepository(session).get(account_id)
    account.meta = {"phone_code_hash": "HASH123"}
    session.commit()

    # Один фейковый клиент обслуживает и логин (connect/sign_in/session.save),
    # и прогрев (client(UpdateStatusRequest) через IDLE_ONLINE).
    client = AsyncMock()
    client.session.save = lambda: "e2e-session-string"
    spy = _SpyTaskQueue()
    ctx = _ctx(
        session,
        now=NOW_INSIDE,
        rng=_FixedRng(WarmingActionType.IDLE_ONLINE),
        client=client,
        task_queue=spy,
    )

    # 1) Логин: код без 2FA → created→warming, прогрев поставлен В ОЧЕРЕДЬ.
    await login_confirm_impl(ctx, account_id, "12345")
    assert AccountRepository(session).get(account_id).status == "warming"
    initial = [args for name, args in spy.enqueued if name == TaskName.WARMING_INITIAL_START]
    assert initial == [(account_id,)]

    # 2) Ускоренная серия tick'ов — initial_start_impl вручную НЕ вызывается.
    for _ in range(50):
        await warming_tick_impl(ctx, account_id)

    assert AccountRepository(session).get(account_id).status == "pool"
    assert _activity_count(session, account_id, kind="initial") == 50


# --- 6. governor 'warming' исчерпан → действие skipped, клиент не тронут (#7) -


async def test_warming_action_skipped_when_rate_limited(session):
    _clean(session)
    account_id = _make_account(session, status="warming", warming_started_at=NOW_INSIDE)
    client = AsyncMock()  # не должен быть вызван
    ctx = _ctx(
        session,
        now=NOW_INSIDE,
        rng=_FixedRng(WarmingActionType.IDLE_ONLINE),
        client=client,
        governor=_DenyGovernor(),
    )

    result = await warming_tick_impl(ctx, account_id)

    assert result == "skipped"
    # действие записано как skipped с причиной rate_limited (не failed)
    acts = session.execute(
        select(WarmingActivity).where(WarmingActivity.account_id == account_id)
    ).scalars().all()
    assert len(acts) == 1
    assert acts[0].status == "skipped"
    assert acts[0].meta == {"reason": "rate_limited"}
    # Telethon-клиент не вызывался
    assert client.await_count == 0
    assert client.call_count == 0
    # аккаунт остаётся в warming
    assert AccountRepository(session).get(account_id).status == "warming"


# --- 7. бан во время прогрева → HealthEvent + banned (#8) --------------------


async def test_warming_action_ban_records_health_event_and_bans(session):
    """UserDeactivatedBan во время warming-действия: раньше был бы просто failed
    без HealthEvent; теперь — session_revoked + переход в banned."""
    from telethon.errors import UserDeactivatedBanError

    _clean(session)
    account_id = _make_account(session, status="warming", warming_started_at=NOW_INSIDE)
    # client(UpdateStatusRequest(...)) в IDLE_ONLINE бросит бан-ошибку
    client = AsyncMock(side_effect=UserDeactivatedBanError(request=_Req()))
    ctx = _ctx(
        session,
        now=NOW_INSIDE,
        rng=_FixedRng(WarmingActionType.IDLE_ONLINE),
        client=client,
    )

    result = await warming_tick_impl(ctx, account_id)

    assert result == "failed"
    # HealthEvent зафиксирован (раньше НЕ создавался — вызов шёл в обход монитора)
    events = session.execute(
        select(HealthEvent).where(
            HealthEvent.account_id == account_id,
            HealthEvent.event_type == "session_revoked",
        )
    ).scalars().all()
    assert len(events) == 1
    # аккаунт переведён в banned через state machine
    assert AccountRepository(session).get(account_id).status == "banned"


# --- 8. warming.tick публикует прогресс в pub/sub (#9) -----------------------


async def test_warming_tick_publishes_progress(session):
    _clean(session)
    account_id = _make_account(session, status="warming", warming_started_at=NOW_INSIDE)
    client = AsyncMock()
    pub = _SpyPublisher()
    ctx = _ctx(
        session,
        now=NOW_INSIDE,
        rng=_FixedRng(WarmingActionType.IDLE_ONLINE),
        client=client,
        publisher=pub,
    )

    result = await warming_tick_impl(ctx, account_id)

    assert result == "done"
    progress = [p for ch, p in pub.events if ch == WARMING_PROGRESS_CHANNEL]
    assert progress == [
        {
            "account_id": account_id,
            "action_type": "idle_online",
            "status": "done",
            "kind": "initial",
        }
    ]
