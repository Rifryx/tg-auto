from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from core.enums import (
    AccountStatus,
    HealthEventType,
    Initiator,
    ProxyStatus,
    ProxyType,
    WarmingActionType,
    WarmingActivityKind,
    WarmingActivityStatus,
    WarmingProfile,
)
from core.repositories import (
    AccountRepository,
    AccountStatusHistoryRepository,
    HealthEventRepository,
    PersonaRepository,
    ProxyRepository,
    WarmingActivityRepository,
)
from core.schemas.account import AccountCreate, AccountUpdate
from core.schemas.health import HealthEventCreate, HealthEventUpdate
from core.schemas.history import AccountStatusHistoryCreate
from core.schemas.persona import PersonaCreate, PersonaUpdate
from core.schemas.proxy import ProxyCreate, ProxyUpdate
from core.schemas.warming import WarmingActivityCreate

_PHONE = iter(range(20_000_000_000, 20_000_100_000))


def _account_create(**overrides) -> AccountCreate:
    defaults = dict(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc-session",
        device_model="Samsung SM-S928B",
        system_version="SDK 34",
        app_version="10.14.5 (5218)",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    defaults.update(overrides)
    return AccountCreate(**defaults)


# --------------------------------------------------------------------------- #
# ProxyRepository
# --------------------------------------------------------------------------- #
def test_proxy_crud(session):
    repo = ProxyRepository(session)

    proxy = repo.create(ProxyCreate(host="1.2.3.4", port=1080, type=ProxyType.SOCKS5, geo="UA"))
    assert proxy.id is not None
    assert proxy.status == ProxyStatus.UNCHECKED.value

    assert repo.get(proxy.id) is proxy

    updated = repo.update(proxy.id, ProxyUpdate(status=ProxyStatus.ALIVE, geo="PL"))
    assert updated is not None
    assert updated.status == ProxyStatus.ALIVE.value
    assert updated.geo == "PL"

    alive = repo.list_by_status(ProxyStatus.ALIVE)
    assert proxy.id in {p.id for p in alive}

    assert repo.delete(proxy.id) is True
    assert repo.get(proxy.id) is None
    assert repo.delete(proxy.id) is False


# --------------------------------------------------------------------------- #
# PersonaRepository
# --------------------------------------------------------------------------- #
def test_persona_crud(session):
    repo = PersonaRepository(session)

    persona = repo.create(PersonaCreate(name="Anna", personality_tags=["curious"]))
    assert persona.id is not None
    assert persona.personality_tags == ["curious"]

    updated = repo.update(persona.id, PersonaUpdate(personality_tags=["calm", "polite"]))
    assert updated is not None
    assert updated.personality_tags == ["calm", "polite"]

    assert repo.delete(persona.id) is True
    assert repo.get(persona.id) is None


# --------------------------------------------------------------------------- #
# AccountRepository — CRUD + селекторы
# --------------------------------------------------------------------------- #
def test_account_create_and_get(session):
    repo = AccountRepository(session)
    acc = repo.create(_account_create())
    assert acc.id is not None
    assert acc.status == AccountStatus.CREATED.value
    assert acc.warming_profile == WarmingProfile.MEDIUM.value
    assert repo.get(acc.id) is acc


def test_account_update_non_status_fields(session):
    repo = AccountRepository(session)
    acc = repo.create(_account_create())

    updated = repo.update(
        acc.id,
        AccountUpdate(username="ivan", bio="hi", warming_profile=WarmingProfile.DENSE),
    )
    assert updated is not None
    assert updated.username == "ivan"
    assert updated.bio == "hi"
    assert updated.warming_profile == WarmingProfile.DENSE.value
    # статус не тронут
    assert updated.status == AccountStatus.CREATED.value


def test_account_list_by_status(session):
    repo = AccountRepository(session)
    a1 = repo.create(_account_create())
    a2 = repo.create(_account_create())

    created = repo.list_by_status(AccountStatus.CREATED)
    ids = {a.id for a in created}
    assert {a1.id, a2.id} <= ids


def test_account_list_pool_by_profile(session):
    repo = AccountRepository(session)
    acc = repo.create(_account_create(warming_profile=WarmingProfile.DENSE))
    # переводим в pool напрямую (эмуляция работы state machine — вне репозитория)
    acc.status = AccountStatus.POOL.value
    session.flush()

    pool_dense = repo.list_pool_by_profile(WarmingProfile.DENSE)
    assert acc.id in {a.id for a in pool_dense}
    assert acc.id not in {a.id for a in repo.list_pool_by_profile(WarmingProfile.MINIMAL)}


def test_account_list_by_assigned_container(session):
    repo = AccountRepository(session)
    acc = repo.create(_account_create())
    acc.status = AccountStatus.ASSIGNED.value
    acc.assigned_container_type = "commenting"
    acc.assigned_container_id = 77
    session.flush()

    found = repo.list_by_assigned_container("commenting", 77)
    assert acc.id in {a.id for a in found}
    assert repo.list_by_assigned_container("commenting", 999) == []


def test_account_list_cooldown_expired(session):
    repo = AccountRepository(session)
    now = datetime.now(timezone.utc)

    expired = repo.create(_account_create())
    expired.status = AccountStatus.COOLDOWN.value
    expired.cooldown_until = now - timedelta(minutes=5)

    future = repo.create(_account_create())
    future.status = AccountStatus.COOLDOWN.value
    future.cooldown_until = now + timedelta(hours=1)
    session.flush()

    ids = {a.id for a in repo.list_cooldown_expired(now)}
    assert expired.id in ids
    assert future.id not in ids


# --------------------------------------------------------------------------- #
# AccountRepository — иммутабельность фингерпринта
# --------------------------------------------------------------------------- #
def test_fingerprint_update_allowed_in_created(session):
    repo = AccountRepository(session)
    acc = repo.create(_account_create())

    updated = repo.update(acc.id, AccountUpdate(device_model="iPhone15,3"))
    assert updated is not None
    assert updated.device_model == "iPhone15,3"


def test_fingerprint_update_rejected_after_created(session):
    repo = AccountRepository(session)
    acc = repo.create(_account_create())
    # аккаунт уже прогревается — фингерпринт трогать нельзя
    acc.status = AccountStatus.WARMING.value
    session.flush()

    with pytest.raises(ValueError):
        repo.update(acc.id, AccountUpdate(device_model="iPhone15,3"))

    # не-фингерпринтные поля по-прежнему обновляются
    ok = repo.update(acc.id, AccountUpdate(username="still-editable"))
    assert ok is not None
    assert ok.username == "still-editable"


# --------------------------------------------------------------------------- #
# AccountRepository — нет способа менять status
# --------------------------------------------------------------------------- #
def test_account_repo_has_no_status_mutator():
    public = [
        name
        for name, _ in inspect.getmembers(AccountRepository, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]
    assert "update_status" not in public
    assert not any("status" in name and name != "list_by_status" for name in public)
    # схема обновления структурно не содержит поля status
    assert "status" not in AccountUpdate.model_fields


# --------------------------------------------------------------------------- #
# WarmingActivityRepository
# --------------------------------------------------------------------------- #
def test_warming_activity_repo(session):
    acc = AccountRepository(session).create(_account_create())
    repo = WarmingActivityRepository(session)

    a1 = repo.create(
        WarmingActivityCreate(
            account_id=acc.id,
            kind=WarmingActivityKind.INITIAL,
            action_type=WarmingActionType.SUBSCRIBE_CHANNEL,
            status=WarmingActivityStatus.DONE,
            target="@durov",
            meta={"channel_id": 1},
        )
    )
    assert a1.id is not None

    repo.create(
        WarmingActivityCreate(
            account_id=acc.id,
            kind=WarmingActivityKind.MAINTENANCE,
            action_type=WarmingActionType.IDLE_ONLINE,
            status=WarmingActivityStatus.SKIPPED,
        )
    )
    items = repo.list_by_account(acc.id)
    assert len(items) == 2


# --------------------------------------------------------------------------- #
# HealthEventRepository
# --------------------------------------------------------------------------- #
def test_health_event_repo(session):
    acc = AccountRepository(session).create(_account_create())
    repo = HealthEventRepository(session)

    ev = repo.create(
        HealthEventCreate(
            account_id=acc.id,
            event_type=HealthEventType.FLOOD_WAIT,
            meta={"seconds": 30},
        )
    )
    assert ev.id is not None
    assert ev.resolved is False

    assert ev.id in {e.id for e in repo.list_unresolved()}
    assert ev.id in {e.id for e in repo.list_by_account(acc.id)}

    resolved = repo.resolve(ev.id)
    assert resolved is not None
    assert resolved.resolved is True
    assert resolved.resolved_at is not None
    assert ev.id not in {e.id for e in repo.list_unresolved()}

    # обновление через update-схему
    repo.update(ev.id, HealthEventUpdate(triggered_status_change="pool→cooldown"))
    assert repo.get(ev.id).triggered_status_change == "pool→cooldown"


# --------------------------------------------------------------------------- #
# AccountStatusHistoryRepository
# --------------------------------------------------------------------------- #
def test_account_status_history_repo(session):
    acc = AccountRepository(session).create(_account_create())
    repo = AccountStatusHistoryRepository(session)

    rec = repo.create(
        AccountStatusHistoryCreate(
            account_id=acc.id,
            from_status=None,
            to_status=AccountStatus.CREATED,
            reason="account.created",
            initiator=Initiator.USER,
        )
    )
    assert rec.id is not None

    repo.create(
        AccountStatusHistoryCreate(
            account_id=acc.id,
            from_status=AccountStatus.CREATED,
            to_status=AccountStatus.WARMING,
            reason="warming.start",
            initiator=Initiator.AUTO,
        )
    )
    history = repo.list_by_account(acc.id)
    assert len(history) == 2
    # порядок — новые первыми
    assert history[0].to_status == AccountStatus.WARMING.value
