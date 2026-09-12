"""Health-монитор: перехват health-инцидентов вокруг вызовов Telethon (§5.3).

:func:`around_telethon_call` оборачивает произвольный вызов Telethon и
классифицирует ошибки в health-инциденты, фиксируя ``HealthEvent`` и (где
применимо) переводя аккаунт через :class:`AccountStateMachine`:

* ``FloodWaitError`` → flood_wait, cooldown на ``seconds`` (health.incident);
* ``UserBannedInChannelError`` / ``ChatWriteForbiddenError`` /
  ``UserIsBlockedError`` → spam_block, cooldown 24ч (health.incident);
* ``AuthKeyUnregisteredError`` / ``SessionRevokedError`` → session_revoked,
  бан (health.ban_detected);
* прочие ``RPCError`` — только warning, инцидентом не считаются.

Исходное исключение всегда пробрасывается дальше — вызывающий сам решает, что
делать с провалом (прогрев → failed-действие, постинг → reschedule и т.п.).
health.incident допустим лишь из pool/assigned — для остальных статусов
переход пропускается (``HealthEvent`` всё равно фиксируется).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, TypeVar

from telethon.errors import (
    AuthKeyUnregisteredError,
    ChatWriteForbiddenError,
    FloodWaitError,
    RPCError,
    SessionRevokedError,
    UserBannedInChannelError,
    UserIsBlockedError,
)

from core.enums import HealthEventType, Initiator
from core.queue.publisher import Publisher
from core.repositories.health_event import HealthEventRepository
from core.schemas.health import HealthEventCreate
from core.state_machine import AccountEvent, AccountStateMachine, TransitionError
from worker.tasks.logging import get_logger

T = TypeVar("T")

SPAM_COOLDOWN_HOURS = 24


async def around_telethon_call(
    call: Callable[[], Awaitable[T]],
    *,
    account_id: int,
    session_factory: Callable[[], Any],
    publisher: Optional[Publisher] = None,
    now: Optional[datetime] = None,
) -> T:
    """Выполняет ``call()``; при health-ошибке фиксирует инцидент и пробрасывает."""
    now = now or datetime.now(timezone.utc)
    try:
        return await call()
    except FloodWaitError as exc:
        _incident(
            session_factory, publisher, account_id,
            HealthEventType.FLOOD_WAIT,
            meta={"seconds": exc.seconds},
            cooldown_until=now + timedelta(seconds=exc.seconds),
        )
        raise
    except (UserBannedInChannelError, ChatWriteForbiddenError, UserIsBlockedError) as exc:
        _incident(
            session_factory, publisher, account_id,
            HealthEventType.SPAM_BLOCK,
            meta={"error": type(exc).__name__},
            cooldown_until=now + timedelta(hours=SPAM_COOLDOWN_HOURS),
        )
        raise
    except (AuthKeyUnregisteredError, SessionRevokedError) as exc:
        _ban(
            session_factory, publisher, account_id,
            HealthEventType.SESSION_REVOKED,
            meta={"error": type(exc).__name__},
        )
        raise
    except RPCError as exc:
        get_logger().warning(
            "health.rpc_error", account_id=account_id, error=repr(exc)
        )
        raise


def _incident(
    session_factory,
    publisher,
    account_id: int,
    event_type: HealthEventType,
    *,
    meta: dict[str, Any],
    cooldown_until: datetime,
) -> None:
    with session_factory() as session:
        event = HealthEventRepository(session).create(
            HealthEventCreate(account_id=account_id, event_type=event_type, meta=meta)
        )
        session.commit()
        try:
            AccountStateMachine(session, publisher).transition(
                account_id,
                AccountEvent.HEALTH_INCIDENT,
                Initiator.HEALTH,
                meta={"cooldown_until": cooldown_until},
            )
            event.triggered_status_change = "cooldown"
            session.commit()
        except (TransitionError, LookupError) as exc:
            get_logger().warning(
                "health.incident_no_transition",
                account_id=account_id,
                event_type=event_type.value,
                error=repr(exc),
            )


def _ban(
    session_factory,
    publisher,
    account_id: int,
    event_type: HealthEventType,
    *,
    meta: dict[str, Any],
) -> None:
    with session_factory() as session:
        event = HealthEventRepository(session).create(
            HealthEventCreate(account_id=account_id, event_type=event_type, meta=meta)
        )
        session.commit()
        try:
            AccountStateMachine(session, publisher).transition(
                account_id, AccountEvent.BAN_DETECTED, Initiator.HEALTH
            )
            event.triggered_status_change = "banned"
            session.commit()
        except (TransitionError, LookupError) as exc:
            get_logger().warning(
                "health.ban_no_transition", account_id=account_id, error=repr(exc)
            )
