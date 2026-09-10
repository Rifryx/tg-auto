from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import fakeredis
import pytest

from core.enums import AccountStatus, Initiator
from core.models import Account
from core.queue.publisher import RedisPublisher
from core.repositories.account import AccountRepository
from core.repositories.account_status_history import AccountStatusHistoryRepository
from core.schemas.account import AccountCreate
from core.state_machine import (
    ACCOUNT_STATUS_CHANNEL,
    AccountEvent,
    AccountStateMachine,
    TransitionError,
)

_PHONE = iter(range(30_000_000_000, 30_000_100_000))
_NOW = datetime.now(timezone.utc)
_COOLDOWN_UNTIL = _NOW + timedelta(hours=6)


class RecordingPublisher:
    """Тестовый паблишер: складывает опубликованные события в список."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, channel: str, payload: dict[str, Any]) -> None:
        self.events.append((channel, dict(payload)))


def _arrange(session, status: AccountStatus, **fields) -> Account:
    """Создаёт аккаунт и выставляет ему нужный для теста статус/поля напрямую
    (эмуляция состояния — сам state machine тестируется отдельным вызовом)."""
    repo = AccountRepository(session)
    acc = repo.create(
        AccountCreate(
            phone=f"+{next(_PHONE)}",
            session_enc=b"enc",
            device_model="Samsung SM-S928B",
            system_version="SDK 34",
            app_version="10.14.5 (5218)",
            lang_code="uk",
            system_lang_code="uk-UA",
        )
    )
    if status is not AccountStatus.CREATED:
        acc.status = status.value
    for k, v in fields.items():
        setattr(acc, k, v)
    session.flush()
    return acc


def _history_count(session, account_id: int) -> int:
    return len(AccountStatusHistoryRepository(session).list_by_account(account_id))


@dataclass
class Case:
    id: str
    from_status: AccountStatus
    event: AccountEvent
    initiator: Initiator
    to_status: AccountStatus
    arrange: dict[str, Any] = field(default_factory=dict)
    meta: Optional[dict[str, Any]] = None
    expected_from: Optional[str] = None  # None => совпадает с from_status.value
    check: Optional[Callable[[Account], None]] = None


_ATTACH_META = {"container_type": "commenting", "container_id": 42}


def _check_warming(acc: Account) -> None:
    assert acc.warming_started_at is not None


def _check_activated(acc: Account) -> None:
    assert acc.activated_at is not None


def _check_attached(acc: Account) -> None:
    assert acc.assigned_container_type == "commenting"
    assert acc.assigned_container_id == 42


def _check_detached(acc: Account) -> None:
    assert acc.assigned_container_type is None
    assert acc.assigned_container_id is None


def _check_cooldown_from_pool(acc: Account) -> None:
    assert acc.previous_status == AccountStatus.POOL.value
    assert acc.cooldown_until == _COOLDOWN_UNTIL


def _check_cooldown_from_assigned(acc: Account) -> None:
    assert acc.previous_status == AccountStatus.ASSIGNED.value
    assert acc.cooldown_until == _COOLDOWN_UNTIL
    # контейнер запоминается (не очищается при уходе в cooldown)
    assert acc.assigned_container_id == 42


def _check_cooldown_cleared(acc: Account) -> None:
    assert acc.cooldown_until is None
    assert acc.previous_status is None


def _check_return_assigned(acc: Account) -> None:
    assert acc.cooldown_until is None
    assert acc.previous_status is None
    assert acc.assigned_container_id == 42  # контейнер сохранён


# По одной записи на КАЖДУЮ разрешённую строку таблицы §1.2.
ALLOWED_CASES = [
    Case("created", AccountStatus.CREATED, AccountEvent.CREATED, Initiator.USER,
         AccountStatus.CREATED, expected_from=None),
    Case("warming_start", AccountStatus.CREATED, AccountEvent.WARMING_START, Initiator.AUTO,
         AccountStatus.WARMING, check=_check_warming),
    Case("warming_completed", AccountStatus.WARMING, AccountEvent.WARMING_COMPLETED, Initiator.AUTO,
         AccountStatus.POOL, check=_check_activated),
    Case("container_attach", AccountStatus.POOL, AccountEvent.CONTAINER_ATTACH, Initiator.USER,
         AccountStatus.ASSIGNED, meta=_ATTACH_META, check=_check_attached),
    Case("container_detach", AccountStatus.ASSIGNED, AccountEvent.CONTAINER_DETACH, Initiator.USER,
         AccountStatus.POOL,
         arrange={"assigned_container_type": "commenting", "assigned_container_id": 42},
         check=_check_detached),
    Case("incident_from_pool", AccountStatus.POOL, AccountEvent.HEALTH_INCIDENT, Initiator.HEALTH,
         AccountStatus.COOLDOWN, meta={"cooldown_until": _COOLDOWN_UNTIL},
         check=_check_cooldown_from_pool),
    Case("incident_from_assigned", AccountStatus.ASSIGNED, AccountEvent.HEALTH_INCIDENT, Initiator.HEALTH,
         AccountStatus.COOLDOWN, meta={"cooldown_until": _COOLDOWN_UNTIL},
         arrange={"assigned_container_type": "commenting", "assigned_container_id": 42},
         check=_check_cooldown_from_assigned),
    Case("cooldown_return_pool", AccountStatus.COOLDOWN, AccountEvent.COOLDOWN_EXPIRED, Initiator.AUTO,
         AccountStatus.POOL,
         arrange={"previous_status": AccountStatus.POOL.value, "cooldown_until": _COOLDOWN_UNTIL},
         expected_from=AccountStatus.COOLDOWN.value, check=_check_cooldown_cleared),
    Case("cooldown_return_assigned", AccountStatus.COOLDOWN, AccountEvent.COOLDOWN_EXPIRED, Initiator.AUTO,
         AccountStatus.ASSIGNED,
         arrange={"previous_status": AccountStatus.ASSIGNED.value, "cooldown_until": _COOLDOWN_UNTIL,
                  "assigned_container_type": "commenting", "assigned_container_id": 42},
         expected_from=AccountStatus.COOLDOWN.value, check=_check_return_assigned),
    Case("retire_from_pool", AccountStatus.POOL, AccountEvent.RETIRE, Initiator.USER,
         AccountStatus.RETIRED),
    Case("retire_from_assigned", AccountStatus.ASSIGNED, AccountEvent.RETIRE, Initiator.USER,
         AccountStatus.RETIRED,
         arrange={"assigned_container_type": "commenting", "assigned_container_id": 42},
         check=_check_detached),  # авто-detach
    Case("ban_from_assigned", AccountStatus.ASSIGNED, AccountEvent.BAN_DETECTED, Initiator.HEALTH,
         AccountStatus.BANNED,
         arrange={"assigned_container_type": "commenting", "assigned_container_id": 42},
         check=_check_detached),
    Case("acknowledge_ban", AccountStatus.BANNED, AccountEvent.ACKNOWLEDGE_BAN, Initiator.USER,
         AccountStatus.RETIRED),
]


@pytest.mark.parametrize("case", ALLOWED_CASES, ids=[c.id for c in ALLOWED_CASES])
def test_allowed_transitions(session, case: Case):
    acc = _arrange(session, case.from_status, **case.arrange)
    pub = RecordingPublisher()
    sm = AccountStateMachine(session, pub)

    result = sm.transition(acc.id, case.event, case.initiator, meta=case.meta)

    # статус обновлён
    assert result.status == case.to_status.value
    assert AccountRepository(session).get(acc.id).status == case.to_status.value

    # побочные эффекты
    if case.check is not None:
        case.check(result)

    # ровно одна запись в истории с корректными from/to/reason/initiator
    history = AccountStatusHistoryRepository(session).list_by_account(acc.id)
    assert len(history) == 1
    rec = history[0]
    expected_from = case.expected_from if case.expected_from is not None else (
        None if case.id == "created" else case.from_status.value
    )
    assert rec.from_status == (None if expected_from is None else AccountStatus(expected_from))
    assert rec.to_status == case.to_status.value
    assert rec.reason == case.event.value
    assert rec.initiator == case.initiator.value

    # ровно одно событие в pub/sub
    assert len(pub.events) == 1
    channel, payload = pub.events[0]
    assert channel == ACCOUNT_STATUS_CHANNEL
    assert payload["account_id"] == acc.id
    assert payload["from"] == expected_from
    assert payload["to"] == case.to_status.value
    assert payload["reason"] == case.event.value
    assert payload["initiator"] == case.initiator.value


@dataclass
class ForbiddenCase:
    id: str
    from_status: AccountStatus
    event: AccountEvent
    initiator: Initiator
    arrange: dict[str, Any] = field(default_factory=dict)
    meta: Optional[dict[str, Any]] = None


FORBIDDEN_CASES = [
    # banned → * (кроме retired): здесь попытка вернуться в pool
    ForbiddenCase("banned_to_pool", AccountStatus.BANNED, AccountEvent.COOLDOWN_EXPIRED,
                  Initiator.AUTO, arrange={"previous_status": AccountStatus.POOL.value}),
    # pool → warming (обратного пути нет)
    ForbiddenCase("pool_to_warming", AccountStatus.POOL, AccountEvent.WARMING_START, Initiator.AUTO),
    # прямой assigned → assigned в другой контейнер
    ForbiddenCase("assigned_to_assigned", AccountStatus.ASSIGNED, AccountEvent.CONTAINER_ATTACH,
                  Initiator.USER,
                  arrange={"assigned_container_type": "commenting", "assigned_container_id": 1},
                  meta={"container_type": "commenting", "container_id": 999}),
    # неверный инициатор для валидного события
    ForbiddenCase("wrong_initiator", AccountStatus.CREATED, AccountEvent.WARMING_START, Initiator.USER),
]


@pytest.mark.parametrize("case", FORBIDDEN_CASES, ids=[c.id for c in FORBIDDEN_CASES])
def test_forbidden_transitions(session, case: ForbiddenCase):
    acc = _arrange(session, case.from_status, **case.arrange)
    pub = RecordingPublisher()
    sm = AccountStateMachine(session, pub)

    with pytest.raises(TransitionError):
        sm.transition(acc.id, case.event, case.initiator, meta=case.meta)

    # статус в БД не изменился, история пуста, событие не улетело
    assert AccountRepository(session).get(acc.id).status == case.from_status.value
    assert _history_count(session, acc.id) == 0
    assert pub.events == []


def test_missing_meta_raises_and_keeps_status(session):
    # container.attach без meta контейнера
    acc = _arrange(session, AccountStatus.POOL)
    sm = AccountStateMachine(session, RecordingPublisher())
    with pytest.raises(TransitionError):
        sm.transition(acc.id, AccountEvent.CONTAINER_ATTACH, Initiator.USER, meta=None)
    assert AccountRepository(session).get(acc.id).status == AccountStatus.POOL.value
    assert _history_count(session, acc.id) == 0

    # health.incident без cooldown_until
    acc2 = _arrange(session, AccountStatus.POOL)
    with pytest.raises(TransitionError):
        sm.transition(acc2.id, AccountEvent.HEALTH_INCIDENT, Initiator.HEALTH, meta={})
    assert AccountRepository(session).get(acc2.id).status == AccountStatus.POOL.value


def test_unknown_event_raises(session):
    acc = _arrange(session, AccountStatus.POOL)
    sm = AccountStateMachine(session, RecordingPublisher())
    with pytest.raises(TransitionError):
        sm.transition(acc.id, "does.not.exist", Initiator.USER)


def test_event_published_to_real_pubsub(session):
    """Событие реально уходит в Redis pub/sub (через fakeredis-клиент)."""
    client = fakeredis.FakeStrictRedis()
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(ACCOUNT_STATUS_CHANNEL)

    acc = _arrange(session, AccountStatus.CREATED)
    sm = AccountStateMachine(session, RedisPublisher(client))
    sm.transition(acc.id, AccountEvent.WARMING_START, Initiator.AUTO)

    message = None
    for _ in range(20):
        message = pubsub.get_message(timeout=0.5)
        if message is not None:
            break
    assert message is not None
    assert message["type"] == "message"
    payload = json.loads(message["data"])
    assert payload == {
        "account_id": acc.id,
        "from": AccountStatus.CREATED.value,
        "to": AccountStatus.WARMING.value,
        "reason": AccountEvent.WARMING_START.value,
        "initiator": Initiator.AUTO.value,
    }
    pubsub.close()
