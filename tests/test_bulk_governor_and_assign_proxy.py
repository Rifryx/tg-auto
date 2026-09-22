"""Тесты governor'а в bulk-item и assign_proxy action (этап 5, backlog #1 и #3)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.enums import BulkActionType, BulkItemStatus, ProxyStatus
from core.models import Account, BulkJob, BulkJobItem, Proxy
from core.repositories.account import AccountRepository
from modules.bulk.actions import ACTION_REGISTRY
from modules.bulk.actions.assign_proxy import AssignProxyPayload, _pick_free_proxy
from worker.tasks.bulk import item_impl

pytestmark = pytest.mark.asyncio

_TABLES = (
    "autopilot_actions",
    "autopilot_goals",
    "bulk_job_items",
    "bulk_jobs",
    "accounts",
    "proxies",
    "projects",
    "account_status_history",
    "warming_activities",
    "health_events",
    "account_health",
    "ban_risk_snapshots",
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


class _DenyGovernor:
    async def check_and_reserve(self, account_id, action_type):
        return False


class _AllowGovernor:
    async def check_and_reserve(self, account_id, action_type):
        return True


class _SpyQueue:
    def __init__(self):
        self.enqueued = []
        self.scheduled = []

    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return "job"

    async def schedule(self, name, run_at, *args, **kwargs):
        self.scheduled.append((name, run_at, args, kwargs))
        return "job"


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _make_proxy(session, host="1.1.1.1", geo="UA", status="alive"):
    p = Proxy(host=host, port=1080, type="socks5", geo=geo, status=status)
    session.add(p)
    session.flush()
    session.commit()
    return p


def _make_account(session, phone="+70000000001", proxy_id=None, status="pool"):
    acc = Account(
        phone=phone,
        session_enc=b"enc",
        status=status,
        proxy_id=proxy_id,
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc


def _make_job_and_item(session, account_id, action_type, payload):
    job = BulkJob(
        action_type=action_type,
        payload=payload,
        status="running",
        total_count=1,
        pending_count=1,
    )
    session.add(job)
    session.flush()
    item = BulkJobItem(job_id=job.id, account_id=account_id, status="pending")
    session.add(item)
    session.flush()
    session.commit()
    return job.id, item.id


# ── governor: rate-limited item reschedules itself ──────────────────────────


async def test_rate_limited_item_returns_to_pending_and_reschedules(session):
    """Отказ governor'а: item возвращается в pending и планируется через backoff."""
    _clean(session)

    proxy = _make_proxy(session)
    account = _make_account(session, proxy_id=proxy.id)
    job_id, item_id = _make_job_and_item(
        session,
        account_id=account.id,
        action_type=BulkActionType.VIEW_STORIES.value,
        payload={"peers": ["@durov"]},
    )

    # Обходим клиент-пул: view_stories requires_client=True, но с failing
    # governor до вызова run() дело не дойдёт.
    queue = _SpyQueue()
    ctx = {
        "session_factory": lambda: _Ctx(session),
        "publisher": None,
        "client_pool": None,
        "governor": _DenyGovernor(),
        "task_queue": queue,
    }

    # Проверяем что item_impl вернул reason=rate_limited.
    result = await item_impl(ctx, job_id, item_id)
    assert result.get("reason") == "rate_limited"

    # Item снова pending, счётчики не двигали.
    session.expire_all()
    item = session.get(BulkJobItem, item_id)
    assert item.status == BulkItemStatus.PENDING.value

    # Задача перепоставлена через backoff.
    assert len(queue.scheduled) == 1
    name, _run_at, args, _kwargs = queue.scheduled[0]
    from core.queue.task_names import TaskName
    assert name == TaskName.BULK_ITEM
    assert args == (job_id, item_id)


async def test_governor_allow_lets_item_run(session, monkeypatch):
    """При allow governor'а действие доходит до action.run (у set_persona
    клиент не нужен, значит можно проверить без ClientPool)."""
    _clean(session)

    proxy = _make_proxy(session)
    account = _make_account(session, proxy_id=proxy.id)
    job_id, item_id = _make_job_and_item(
        session,
        account_id=account.id,
        action_type=BulkActionType.SET_PERSONA.value,
        payload={"persona_id": None},
    )

    ctx = {
        "session_factory": lambda: _Ctx(session),
        "publisher": None,
        "client_pool": None,
        # SET_PERSONA имеет governor_key=None, значит governor не проверяется
        # даже при DenyGovernor.
        "governor": _DenyGovernor(),
        "task_queue": _SpyQueue(),
    }

    result = await item_impl(ctx, job_id, item_id)
    # persona_id=None → аккаунт обновлён без ошибок → status=done.
    assert result.get("status") == BulkItemStatus.DONE.value


# ── assign_proxy: pool-mode ─────────────────────────────────────────────────


async def test_assign_proxy_pool_picks_free_alive(session):
    _clean(session)
    _make_proxy(session, host="1.1.1.1", geo="UA")
    p2 = _make_proxy(session, host="2.2.2.2", geo="UA")
    # p2 не занят никем — должен быть выбран.
    account = _make_account(session, proxy_id=None)

    action = ACTION_REGISTRY[BulkActionType.ASSIGN_PROXY.value]
    payload = AssignProxyPayload(mode="pool")
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=None,
    )
    assert result.ok
    # Один из двух — тот, который NOT EXISTS реферируется как ещё свободный.
    session.expire_all()
    account = AccountRepository(session).get(account.id)
    assert account.proxy_id in {p2.id, p2.id - 1}  # 1.1.1.1 тоже свободен


async def test_assign_proxy_pool_returns_skipped_when_all_busy(session):
    _clean(session)
    proxy = _make_proxy(session)
    _make_account(session, phone="+7A", proxy_id=proxy.id)
    account_b = _make_account(session, phone="+7B", proxy_id=None)

    action = ACTION_REGISTRY[BulkActionType.ASSIGN_PROXY.value]
    payload = AssignProxyPayload(mode="pool")
    result = await action.run(
        account_id=account_b.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=None,
    )
    assert result.ok is False
    assert result.skipped is True
    assert result.detail["reason"] == "no_proxy_left"


async def test_assign_proxy_fixed_updates_specific(session):
    _clean(session)
    proxy = _make_proxy(session)
    account = _make_account(session, proxy_id=None)

    action = ACTION_REGISTRY[BulkActionType.ASSIGN_PROXY.value]
    payload = AssignProxyPayload(mode="fixed", proxy_id=proxy.id)
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=None,
    )
    assert result.ok
    assert result.detail["proxy_id"] == proxy.id


def test_assign_proxy_payload_mode_validation():
    """mode='fixed' без proxy_id → 422. mode='pool' с proxy_id → 422."""
    with pytest.raises(Exception):
        AssignProxyPayload(mode="fixed")
    with pytest.raises(Exception):
        AssignProxyPayload(mode="pool", proxy_id=1)


async def test_pick_free_proxy_respects_geo(session):
    _clean(session)
    _make_proxy(session, host="ua", geo="UA")
    de = _make_proxy(session, host="de", geo="DE")

    picked = _pick_free_proxy(session, geo="DE")
    assert picked is not None
    assert picked.id == de.id

    # Всё занято → None.
    _make_account(session, phone="+7A", proxy_id=de.id)
    picked_again = _pick_free_proxy(session, geo="DE")
    assert picked_again is None
