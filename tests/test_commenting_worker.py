"""Интеграционные тесты раннера commenting на моках (PROJECT-STAGES §5, §8.3).

БД настоящая; LLM/ClientPool/governor/Telethon — фейки; now/rng инъектируются.
Таблицы чистятся в начале каждого теста.
"""

from __future__ import annotations

import itertools
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from telethon.errors import FloodWaitError

from core.models import Account, CampaignAccount
from core.repositories.account import AccountRepository
from modules.commenting.repositories import CampaignRepository, CommentLogRepository
from modules.commenting.schemas import CampaignCreate
from modules.commenting.worker import listener, registry, runner
from core.queue.task_names import TaskName

pytestmark = pytest.mark.asyncio

NOW_INSIDE = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)   # 12:00 UTC → в окне
NOW_OUTSIDE = datetime(2026, 9, 12, 3, 0, tzinfo=timezone.utc)   # 03:00 UTC → вне окна
_PHONE = itertools.count(96_000_000_000)
_TABLES = (
    "accounts",
    "health_events",
    "account_status_history",
    "warming_activities",
    '"commenting".campaigns',
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)


class _Req:
    pass


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued = []
        self.scheduled = []

    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return "job"

    async def schedule(self, name, run_at, *args, **kwargs):
        self.scheduled.append((name, run_at, args, kwargs))
        return "job"


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.released = []

    async def get(self, account_id):
        return self._client

    async def release(self, account_id):
        self.released.append(account_id)


class _FakeGovernor:
    def __init__(self, allow=True):
        self.allow = allow

    async def check_and_reserve(self, account_id, action_type):
        return self.allow


class _FakeLLM:
    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        return "auto-generated comment"


class _Rng:
    """Управляемый RNG: random() фиксирован, остальное — детерминированно."""

    def __init__(self, random_value=0.9, seed=0):
        self._random_value = random_value
        self._counter = seed

    def random(self):
        return self._random_value

    def randint(self, a, b):
        return b

    def uniform(self, a, b):
        self._counter += 1
        return a + (b - a) * ((self._counter * 0.37) % 1.0)

    def sample(self, population, k):
        return list(population)[:k]

    def choice(self, seq):
        return seq[0]

    def shuffle(self, seq):
        pass


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _make_campaign(session, *, hours=(9, 23)) -> int:
    c = CampaignRepository(session).create(
        CampaignCreate(
            name="camp",
            target_channel="@ch",
            base_system_prompt="comment nicely",
            llm_provider="deepseek",
            active_hours_start=time(hours[0], 0),
            active_hours_end=time(hours[1], 0),
            active_hours_tz="UTC",
            posting_delay_min_sec=10,
            posting_delay_max_sec=60,
            discussion_group_id=555,
        )
    )
    session.commit()
    return c.id


def _make_assigned(session, campaign_id: int) -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status="assigned",
        assigned_container_type="commenting",
        assigned_container_id=campaign_id,
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    session.add(CampaignAccount(campaign_id=campaign_id, account_id=acc.id))
    session.commit()
    return acc.id


def _ctx(session, *, now, rng, task_queue, client=None, governor=None):
    return {
        "session_factory": _factory(session),
        "now": now,
        "rng": rng,
        "task_queue": task_queue,
        "client_pool": _FakePool(client) if client is not None else None,
        "governor": governor,
        "llm_provider": _FakeLLM(),
        "publisher": None,
    }


# --- 1. новый пост → 2-4 post_comment с уникальными аккаунтами ----------------


async def test_new_post_schedules_unique_comments(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    ids = {_make_assigned(session, campaign_id) for _ in range(3)}

    spy = _SpyTaskQueue()
    # handler ловит пост канала (sender_id == channel_id)
    handler = listener.make_new_post_handler(campaign_id, spy, channel_id=777)
    await handler(SimpleNamespace(message=SimpleNamespace(sender_id=777, id=100)))
    await handler(SimpleNamespace(message=SimpleNamespace(sender_id=111, id=101)))  # чужой — игнор
    assert spy.enqueued == [(TaskName.COMMENTING_ON_NEW_POST, (campaign_id, 100), {})]

    import random as _r
    ctx = _ctx(session, now=NOW_INSIDE, rng=_r.Random(42), task_queue=spy, governor=_FakeGovernor())
    count = await runner.on_new_post(ctx, campaign_id, 100)

    assert 2 <= count <= 4
    assert len(spy.scheduled) == count
    accounts = [args[1] for _, _, args, _ in spy.scheduled]
    assert len(set(accounts)) == count            # уникальные аккаунты
    assert set(accounts) <= ids
    run_ats = [run_at for _, run_at, _, _ in spy.scheduled]
    assert len(set(run_ats)) == count             # разные задержки


# --- 2. post_comment отправляет и пишет CommentLog ---------------------------


async def test_post_comment_posts_and_logs(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)

    client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=999)))
    spy = _SpyTaskQueue()
    ctx = _ctx(session, now=NOW_INSIDE, rng=_Rng(random_value=0.9), task_queue=spy,
               client=client, governor=_FakeGovernor(allow=True))

    result = await runner.post_comment(ctx, campaign_id, account_id, "hello", 100, 100)

    assert result == 999
    client.send_message.assert_awaited_once()
    logs = CommentLogRepository(session).list_by_campaign(campaign_id)
    assert len(logs) == 1
    assert logs[0].status == "posted"
    assert logs[0].posted_message_id == 999
    assert ctx["client_pool"].released == [account_id]


# --- 3. тред-симуляция: 0.35 форсирован; глубина > 3 не допускается ----------


async def test_thread_simulation_and_depth_cap(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)
    client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=999)))

    # rng.random()=0.1 < 0.35 → продолжение треда
    spy = _SpyTaskQueue()
    ctx = _ctx(session, now=NOW_INSIDE, rng=_Rng(random_value=0.1), task_queue=spy,
               client=client, governor=_FakeGovernor())
    await runner.post_comment(ctx, campaign_id, account_id, "hi", 100, 100, thread_depth=0)

    cont = [e for e in spy.enqueued if e[0] == TaskName.COMMENTING_ON_NEW_POST]
    assert len(cont) == 1
    assert cont[0][2]["in_reply_to"] == 999
    assert cont[0][2]["thread_depth"] == 1

    # глубина 3 → нет продолжения даже при 0.1
    spy2 = _SpyTaskQueue()
    ctx2 = _ctx(session, now=NOW_INSIDE, rng=_Rng(random_value=0.1), task_queue=spy2,
                client=client, governor=_FakeGovernor())
    await runner.post_comment(ctx2, campaign_id, account_id, "hi", 100, 999, thread_depth=3)
    assert not [e for e in spy2.enqueued if e[0] == TaskName.COMMENTING_ON_NEW_POST]


# --- 4. вне active_hours → skip, без ретрая ----------------------------------


async def test_post_comment_outside_hours_skips(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)
    client = SimpleNamespace(send_message=AsyncMock())
    spy = _SpyTaskQueue()
    ctx = _ctx(session, now=NOW_OUTSIDE, rng=_Rng(), task_queue=spy,
               client=client, governor=_FakeGovernor())

    result = await runner.post_comment(ctx, campaign_id, account_id, "hi", 100, 100)

    assert result is None
    client.send_message.assert_not_awaited()
    assert CommentLogRepository(session).list_by_campaign(campaign_id) == []
    assert spy.scheduled == []  # не ретраится


# --- 5. governor лимит → reschedule через 5 мин ------------------------------


async def test_post_comment_rate_limited_reschedules(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)
    client = SimpleNamespace(send_message=AsyncMock())
    spy = _SpyTaskQueue()
    ctx = _ctx(session, now=NOW_INSIDE, rng=_Rng(), task_queue=spy,
               client=client, governor=_FakeGovernor(allow=False))

    result = await runner.post_comment(ctx, campaign_id, account_id, "hi", 100, 100)

    assert result is None
    client.send_message.assert_not_awaited()
    assert CommentLogRepository(session).list_by_campaign(campaign_id) == []
    assert len(spy.scheduled) == 1
    name, run_at, _, _ = spy.scheduled[0]
    assert name == TaskName.COMMENTING_POST_COMMENT
    assert run_at == NOW_INSIDE + timedelta(minutes=5)


# --- 6. FloodWait → health-инцидент + cooldown, кампания пропускает ----------


async def test_post_comment_flood_wait_cooldown(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)

    def _raise(*a, **k):
        raise FloodWaitError(request=_Req(), capture=60)

    client = SimpleNamespace(send_message=AsyncMock(side_effect=_raise))
    spy = _SpyTaskQueue()
    ctx = _ctx(session, now=NOW_INSIDE, rng=_Rng(), task_queue=spy,
               client=client, governor=_FakeGovernor())

    with pytest.raises(FloodWaitError):
        await runner.post_comment(ctx, campaign_id, account_id, "hi", 100, 100)

    account = AccountRepository(session).get(account_id)
    assert account.status == "cooldown"
    assert ctx["client_pool"].released == [account_id]  # клиент отпущен

    # health-событие записано
    from core.models import HealthEvent
    from sqlalchemy import select
    events = session.execute(
        select(HealthEvent).where(
            HealthEvent.account_id == account_id, HealthEvent.event_type == "flood_wait"
        )
    ).scalars().all()
    assert len(events) == 1

    # кампания пропускает аккаунт в cooldown в следующий раз
    import random as _r
    count = await runner.on_new_post(
        _ctx(session, now=NOW_INSIDE, rng=_r.Random(1), task_queue=_SpyTaskQueue(),
             governor=_FakeGovernor()),
        campaign_id, 100,
    )
    assert count == 0


# --- 7. e2e в одном процессе: attach слушателя → NewMessage → comment_logs ----


class _ListenerClient:
    """Клиент, покрывающий и attach (get_entity/handlers), и постинг (send_message)."""

    def __init__(self, channel_id: int):
        self._channel_id = channel_id
        self.added: list = []
        self.send_message = AsyncMock(return_value=SimpleNamespace(id=999))

    async def get_entity(self, target):
        return SimpleNamespace(id=self._channel_id)

    def add_event_handler(self, handler, event):
        self.added.append((handler, event))

    def remove_event_handler(self, handler, event):
        self.added = [(h, e) for h, e in self.added if h is not handler]


async def test_registry_attach_to_comment_logs_single_process(session):
    """created→enabled→attach аккаунт→NewMessage→comment_logs, без рестарта."""
    _clean(session)
    campaign_id = _make_campaign(session)          # enabled по умолчанию
    account_id = _make_assigned(session, campaign_id)

    channel_id = 777
    client = _ListenerClient(channel_id)
    spy = _SpyTaskQueue()
    ctx = _ctx(session, now=NOW_INSIDE, rng=_Rng(random_value=0.9), task_queue=spy,
               client=client, governor=_FakeGovernor(allow=True))

    # 1) Подключаем слушатель одной кампании через реестр (attach).
    reg = registry.ListenerRegistry()
    assert await reg.attach(campaign_id, ctx) is True
    assert reg.active() == [campaign_id]
    assert len(client.added) == 1
    handler, _event = client.added[0]

    # 2) Прилетает пост самого канала в discussion group → handler ставит on_new_post.
    await handler(SimpleNamespace(message=SimpleNamespace(sender_id=channel_id, id=100)))
    assert spy.enqueued == [(TaskName.COMMENTING_ON_NEW_POST, (campaign_id, 100), {})]

    # 3) Прогоняем on_new_post → post_comment (как это сделал бы воркер).
    scheduled = await runner.on_new_post(ctx, campaign_id, 100)
    assert scheduled >= 1
    for _name, _run_at, args, kwargs in spy.scheduled:
        await runner.post_comment(ctx, *args, **kwargs)

    # 4) comment_logs заполнился — весь путь отработал в одном процессе.
    logs = CommentLogRepository(session).list_by_campaign(campaign_id)
    assert len(logs) == scheduled
    assert all(log.status == "posted" for log in logs)

    # detach снимает слушатель (запись остаётся — это чистка листенера).
    assert await reg.detach(campaign_id) is True
    assert reg.active() == []
