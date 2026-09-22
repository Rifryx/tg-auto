"""Health-монитор: перехват health-инцидентов вокруг вызовов Telethon (§5.3).

:func:`around_telethon_call` оборачивает произвольный вызов Telethon и
классифицирует ошибки в health-инциденты, фиксируя ``HealthEvent`` и (где
применимо) переводя аккаунт через :class:`AccountStateMachine`:

* ``FloodWaitError`` → flood_wait, cooldown на ``seconds`` (health.incident);
  при ``handle_flood_wait=False`` НЕ обрабатывается тут, а пробрасывается как
  есть (login-flow разбирает флудвейт сам: waiting_code/waiting_password);
* ``SessionPasswordNeededError`` → НЕ инцидент (штатный шаг 2FA): пробрасывается
  нетронутым, без ``HealthEvent`` и без warning;
* ``UserBannedInChannelError`` / ``ChatWriteForbiddenError`` /
  ``UserIsBlockedError`` → spam_block, cooldown 24ч (health.incident);
* ``AuthKeyUnregisteredError`` / ``SessionRevokedError`` /
  ``UserDeactivatedBanError`` / ``UserDeactivatedError`` /
  ``PhoneNumberBannedError`` → session_revoked, бан (health.ban_detected);
* прочие ``RPCError`` — только warning, инцидентом не считаются.

Исходное исключение всегда пробрасывается дальше — вызывающий сам решает, что
делать с провалом (прогрев → failed-действие, постинг → reschedule и т.п.).
health.incident допустим лишь из pool/assigned — для остальных статусов
переход пропускается (``HealthEvent`` всё равно фиксируется). health.ban_detected
допустим из большинства статусов (включая created/warming), поэтому бан ловится
и во время логина, и во время прогрева.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, TypeVar

from telethon.errors import (
    AuthKeyUnregisteredError,
    ChatWriteForbiddenError,
    FloodWaitError,
    PhoneNumberBannedError,
    RPCError,
    SessionPasswordNeededError,
    SessionRevokedError,
    UserBannedInChannelError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    UserIsBlockedError,
)

import structlog

from core.enums import HealthEventType, Initiator, TriggeredStatusChange
from core.queue.publisher import Publisher
from core.repositories.health_event import HealthEventRepository
from core.schemas.health import HealthEventCreate
from core.state_machine import AccountEvent, AccountStateMachine, TransitionError

# worker.health не зависит от worker.tasks (иначе цикл: worker.tasks.__init__
# импортирует login/warming/commenting, а те — worker.health). Логгер берём
# напрямую из structlog — конфигурация процессоров глобальна (configure_logging).
get_logger = structlog.get_logger

T = TypeVar("T")

SPAM_COOLDOWN_HOURS = 24

# Канал pub/sub с health-алертами (аудит #9). Дашборд может опрашивать БД, но
# канал существует для «живых» алертов.
HEALTH_ALERT_CHANNEL = "health_alert"

# severity деривируется из типа события (отдельной колонки нет — §1.3/§5.3).
_SEVERITY: dict[str, str] = {
    HealthEventType.FLOOD_WAIT.value: "warning",
    HealthEventType.PROXY_DOWN.value: "warning",
    HealthEventType.RESTRICTED.value: "critical",
    HealthEventType.SPAM_BLOCK.value: "critical",
    HealthEventType.SESSION_REVOKED.value: "critical",
    HealthEventType.AUTH_FAILED.value: "critical",
}


def _severity(event_type: HealthEventType) -> str:
    return _SEVERITY.get(event_type.value, "warning")


def _publish_alert(publisher, account_id: int, event_type: HealthEventType) -> None:
    if publisher is None:
        return
    publisher.publish(
        HEALTH_ALERT_CHANNEL,
        {
            "account_id": account_id,
            "event_type": event_type.value,
            "severity": _severity(event_type),
        },
    )


async def around_telethon_call(
    call: Callable[[], Awaitable[T]],
    *,
    account_id: int,
    session_factory: Callable[[], Any],
    publisher: Optional[Publisher] = None,
    now: Optional[datetime] = None,
    handle_flood_wait: bool = True,
) -> T:
    """Выполняет ``call()``; при health-ошибке фиксирует инцидент и пробрасывает.

    ``handle_flood_wait=False`` — не трогать ``FloodWaitError`` (его разбирает
    вызывающий, напр. login-flow): исключение пробрасывается без ``HealthEvent``.
    """
    now = now or datetime.now(timezone.utc)
    try:
        return await call()
    except SessionPasswordNeededError:
        # Штатный шаг 2FA — не инцидент: пробрасываем нетронутым.
        raise
    except FloodWaitError as exc:
        if not handle_flood_wait:
            raise
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
    except (
        AuthKeyUnregisteredError,
        SessionRevokedError,
        UserDeactivatedBanError,
        UserDeactivatedError,
        PhoneNumberBannedError,
    ) as exc:
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
            event.triggered_status_change = TriggeredStatusChange.COOLDOWN.value
            session.commit()
        except (TransitionError, LookupError) as exc:
            get_logger().warning(
                "health.incident_no_transition",
                account_id=account_id,
                event_type=event_type.value,
                error=repr(exc),
            )
    _publish_alert(publisher, account_id, event_type)


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
            event.triggered_status_change = TriggeredStatusChange.BANNED.value
            session.commit()
        except (TransitionError, LookupError) as exc:
            get_logger().warning(
                "health.ban_no_transition", account_id=account_id, error=repr(exc)
            )
    _publish_alert(publisher, account_id, event_type)
