"""AccountStateMachine — единственная точка смены ``accounts.status``.

Реализует таблицу переходов PROJECT-STAGES §1.2 как декларативную структуру
(`_TRANSITIONS`) и применяет её в §1.4-семантике: проверка разрешённости,
побочные эффекты и запись в ``account_status_history`` — в одной транзакции,
затем публикация события в Redis pub/sub.

Никакой логики сверх таблицы переходов здесь нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Optional

from sqlalchemy.orm import Session

from core.enums import AccountStatus, Initiator
from core.models import Account
from core.queue.publisher import Publisher
from core.repositories.account import AccountRepository
from core.repositories.account_status_history import AccountStatusHistoryRepository
from core.schemas.history import AccountStatusHistoryCreate

ACCOUNT_STATUS_CHANNEL = "account_status"


class TransitionError(Exception):
    """Переход не разрешён таблицей §1.2."""


class AccountEvent(str, Enum):
    """События переходов (PROJECT-STAGES §1.2)."""

    CREATED = "account.created"
    WARMING_START = "warming.start"
    WARMING_COMPLETED = "warming.completed"
    CONTAINER_ATTACH = "container.attach"
    CONTAINER_DETACH = "container.detach"
    HEALTH_INCIDENT = "health.incident"
    COOLDOWN_EXPIRED = "cooldown.expired"
    RETIRE = "account.retire"
    RESTORE = "account.restore"
    BAN_DETECTED = "health.ban_detected"
    ACKNOWLEDGE_BAN = "account.acknowledge_ban"


class Effect(str, Enum):
    """Атомарные побочные эффекты перехода."""

    SET_WARMING_STARTED = "set_warming_started"
    SET_ACTIVATED = "set_activated"
    ATTACH_CONTAINER = "attach_container"
    DETACH_CONTAINER = "detach_container"
    ENTER_COOLDOWN = "enter_cooldown"
    EXIT_COOLDOWN = "exit_cooldown"


# Множества источников для «любая (кроме …)» строк §1.2.
_RETIRE_FROM = frozenset(
    {
        AccountStatus.CREATED,
        AccountStatus.WARMING,
        AccountStatus.POOL,
        AccountStatus.ASSIGNED,
        AccountStatus.COOLDOWN,
    }
)
_BAN_FROM = frozenset(
    {
        AccountStatus.CREATED,
        AccountStatus.WARMING,
        AccountStatus.POOL,
        AccountStatus.ASSIGNED,
        AccountStatus.COOLDOWN,
        AccountStatus.RETIRED,
    }
)


@dataclass(frozen=True)
class _Transition:
    event: AccountEvent
    # None — строка «— → created» (нет предыдущего статуса).
    from_states: Optional[frozenset[AccountStatus]]
    to_state: AccountStatus
    initiator: Initiator
    effects: tuple[Effect, ...] = ()
    # Дополнительное условие (напр. cooldown.expired зависит от previous_status).
    guard: Optional[Callable[[Account], bool]] = None


def _prev_is(status: AccountStatus) -> Callable[[Account], bool]:
    return lambda acc: acc.previous_status == status.value


def _prev_assigned_with_container(acc: Account) -> bool:
    return (
        acc.previous_status == AccountStatus.ASSIGNED.value
        and acc.assigned_container_id is not None
    )


# Таблица переходов §1.2 — единый источник правды.
_TRANSITIONS: tuple[_Transition, ...] = (
    _Transition(
        AccountEvent.CREATED, None, AccountStatus.CREATED, Initiator.USER
    ),
    _Transition(
        AccountEvent.WARMING_START,
        frozenset({AccountStatus.CREATED}),
        AccountStatus.WARMING,
        Initiator.AUTO,
        effects=(Effect.SET_WARMING_STARTED,),
    ),
    _Transition(
        AccountEvent.WARMING_COMPLETED,
        frozenset({AccountStatus.WARMING}),
        AccountStatus.POOL,
        Initiator.AUTO,
        effects=(Effect.SET_ACTIVATED,),
    ),
    _Transition(
        AccountEvent.CONTAINER_ATTACH,
        frozenset({AccountStatus.POOL}),
        AccountStatus.ASSIGNED,
        Initiator.USER,
        effects=(Effect.ATTACH_CONTAINER,),
    ),
    _Transition(
        AccountEvent.CONTAINER_DETACH,
        frozenset({AccountStatus.ASSIGNED}),
        AccountStatus.POOL,
        Initiator.USER,
        effects=(Effect.DETACH_CONTAINER,),
    ),
    _Transition(
        AccountEvent.HEALTH_INCIDENT,
        frozenset({AccountStatus.POOL}),
        AccountStatus.COOLDOWN,
        Initiator.HEALTH,
        effects=(Effect.ENTER_COOLDOWN,),
    ),
    _Transition(
        AccountEvent.HEALTH_INCIDENT,
        frozenset({AccountStatus.ASSIGNED}),
        AccountStatus.COOLDOWN,
        Initiator.HEALTH,
        effects=(Effect.ENTER_COOLDOWN,),
    ),
    _Transition(
        AccountEvent.COOLDOWN_EXPIRED,
        frozenset({AccountStatus.COOLDOWN}),
        AccountStatus.POOL,
        Initiator.AUTO,
        effects=(Effect.EXIT_COOLDOWN,),
        guard=_prev_is(AccountStatus.POOL),
    ),
    _Transition(
        AccountEvent.COOLDOWN_EXPIRED,
        frozenset({AccountStatus.COOLDOWN}),
        AccountStatus.ASSIGNED,
        Initiator.AUTO,
        effects=(Effect.EXIT_COOLDOWN,),
        guard=_prev_assigned_with_container,
    ),
    _Transition(
        AccountEvent.RETIRE,
        _RETIRE_FROM,
        AccountStatus.RETIRED,
        Initiator.USER,
        # Если был assigned — сначала автоматический detach (в этой же транзакции).
        effects=(Effect.DETACH_CONTAINER,),
    ),
    _Transition(
        AccountEvent.BAN_DETECTED,
        _BAN_FROM,
        AccountStatus.BANNED,
        Initiator.HEALTH,
        effects=(Effect.DETACH_CONTAINER,),
    ),
    _Transition(
        AccountEvent.ACKNOWLEDGE_BAN,
        frozenset({AccountStatus.BANNED}),
        AccountStatus.RETIRED,
        Initiator.USER,
    ),
    # Возврат выведенного аккаунта в пул (пользователь решает попробовать снова).
    _Transition(
        AccountEvent.RESTORE,
        frozenset({AccountStatus.RETIRED}),
        AccountStatus.POOL,
        Initiator.USER,
    ),
)


def _json_safe(meta: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    if not meta:
        return None
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in meta.items()}


class AccountStateMachine:
    """Переключает ``accounts.status`` строго по таблице §1.2."""

    def __init__(self, session: Session, publisher: Optional[Publisher] = None) -> None:
        self._session = session
        self._accounts = AccountRepository(session)
        self._history = AccountStatusHistoryRepository(session)
        self._publisher = publisher

    def transition(
        self,
        account_id: int,
        event: AccountEvent | str,
        initiator: Initiator | str,
        meta: Optional[Mapping[str, Any]] = None,
    ) -> Account:
        try:
            event = AccountEvent(event)
        except ValueError as exc:
            raise TransitionError(f"unknown event '{event}'") from exc
        initiator = Initiator(initiator)
        meta = dict(meta or {})

        account = self._accounts.get(account_id)
        if account is None:
            raise LookupError(f"account {account_id} not found")

        current = account.status
        rule = self._resolve(event, current, account, initiator)

        self._require_meta(rule, meta)

        from_status = None if rule.from_states is None else current
        now = datetime.now(timezone.utc)
        self._apply_effects(account, rule, meta, from_status, now)
        account.status = rule.to_state.value

        self._history.create(
            AccountStatusHistoryCreate(
                account_id=account.id,
                from_status=from_status,
                to_status=rule.to_state,
                reason=event.value,
                initiator=initiator,
                meta=_json_safe(meta),
            )
        )

        self._session.commit()

        self._publish(account.id, from_status, rule.to_state.value, event.value, initiator.value)
        return account

    # ------------------------------------------------------------------ #
    def _resolve(
        self,
        event: AccountEvent,
        current: str,
        account: Account,
        initiator: Initiator,
    ) -> _Transition:
        by_event = [t for t in _TRANSITIONS if t.event == event]

        from_ok: list[_Transition] = []
        for t in by_event:
            if t.from_states is None:
                if current == AccountStatus.CREATED.value and account.previous_status is None:
                    from_ok.append(t)
            elif current in {s.value for s in t.from_states}:
                from_ok.append(t)

        if not from_ok:
            raise TransitionError(
                f"transition '{event.value}' is not allowed from status '{current}'"
            )

        guard_ok = [t for t in from_ok if t.guard is None or t.guard(account)]
        if not guard_ok:
            raise TransitionError(
                f"transition '{event.value}' from '{current}' blocked by precondition "
                f"(previous_status={account.previous_status})"
            )
        if len(guard_ok) > 1:  # защита от неоднозначной таблицы
            raise TransitionError(f"ambiguous transition for '{event.value}' from '{current}'")

        rule = guard_ok[0]
        if initiator != rule.initiator:
            raise TransitionError(
                f"event '{event.value}' requires initiator '{rule.initiator.value}', "
                f"got '{initiator.value}'"
            )
        return rule

    @staticmethod
    def _require_meta(rule: _Transition, meta: Mapping[str, Any]) -> None:
        if Effect.ATTACH_CONTAINER in rule.effects:
            if meta.get("container_type") is None or meta.get("container_id") is None:
                raise TransitionError(
                    "container.attach requires meta 'container_type' and 'container_id'"
                )
        if Effect.ENTER_COOLDOWN in rule.effects and meta.get("cooldown_until") is None:
            raise TransitionError("health.incident requires meta 'cooldown_until'")

    @staticmethod
    def _apply_effects(
        account: Account,
        rule: _Transition,
        meta: Mapping[str, Any],
        from_status: Optional[str],
        now: datetime,
    ) -> None:
        for effect in rule.effects:
            if effect is Effect.SET_WARMING_STARTED:
                account.warming_started_at = now
            elif effect is Effect.SET_ACTIVATED:
                account.activated_at = now
            elif effect is Effect.ATTACH_CONTAINER:
                account.assigned_container_type = meta["container_type"]
                account.assigned_container_id = meta["container_id"]
            elif effect is Effect.DETACH_CONTAINER:
                account.assigned_container_type = None
                account.assigned_container_id = None
            elif effect is Effect.ENTER_COOLDOWN:
                account.previous_status = from_status
                account.cooldown_until = meta["cooldown_until"]
            elif effect is Effect.EXIT_COOLDOWN:
                account.cooldown_until = None
                account.previous_status = None

    def _publish(
        self,
        account_id: int,
        from_status: Optional[str],
        to_status: str,
        reason: str,
        initiator: str,
    ) -> None:
        if self._publisher is None:
            return
        self._publisher.publish(
            ACCOUNT_STATUS_CHANNEL,
            {
                "account_id": account_id,
                "from": from_status,
                "to": to_status,
                "reason": reason,
                "initiator": initiator,
            },
        )
