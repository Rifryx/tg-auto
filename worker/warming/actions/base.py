"""Общий каркас действий прогрева: результат и обёртка try/except."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, Union

from core.enums import WarmingActionType, WarmingActivityStatus
from core.models import Account
from worker.health import around_telethon_call
from worker.tasks.logging import get_logger

# Небольшой пул публичных целей для действий прогрева (реестра интересов пока
# нет — берём общеизвестные публичные каналы/группы).
DISCOVERY_CHANNELS = ("telegram", "durov", "tginfo")
DISCOVERY_GROUPS = ("python", "telegramdesktop")


@dataclass
class WarmingActionResult:
    action_type: WarmingActionType
    status: WarmingActivityStatus
    target: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


# Тело действия возвращает целевой объект (str) или None; исключения ловит обёртка.
_ActionBody = Callable[..., Awaitable[Union[str, None]]]


def action(action_type: WarmingActionType) -> Callable[[_ActionBody], _ActionBody]:
    """Оборачивает тело действия: успех → done, любое исключение → failed.

    Тело действия выполняется через :func:`around_telethon_call` — health-ошибки
    Telethon (бан/spam/session_revoked) фиксируются как ``HealthEvent`` и (где
    применимо) переводят аккаунт через state machine, ПОСЛЕ чего исключение
    пробрасывается и ловится тут же → ``status=failed``. Таким образом ни одно
    сетевое исключение не роняет tick, но health-события больше не теряются
    (аудит #8). ``session_factory``/``publisher``/``now`` приходят из ctx tick'а.
    """

    def decorator(body: _ActionBody):
        async def execute(
            client,
            account: Account,
            *,
            session_factory: Optional[Callable[[], Any]] = None,
            publisher: Any = None,
            now: Optional[datetime] = None,
        ) -> WarmingActionResult:
            try:
                if session_factory is None:
                    # Без ctx (напр. прямой вызов в старых тестах) — без health-обёртки.
                    target = await body(client, account)
                else:
                    target = await around_telethon_call(
                        lambda: body(client, account),
                        account_id=account.id,
                        session_factory=session_factory,
                        publisher=publisher,
                        now=now,
                    )
                return WarmingActionResult(
                    action_type, WarmingActivityStatus.DONE, target=target
                )
            except Exception as exc:  # noqa: BLE001 - действие изолировано
                get_logger().warning(
                    "warming.action_failed",
                    action=action_type.value,
                    account_id=account.id,
                    error=repr(exc),
                )
                return WarmingActionResult(
                    action_type,
                    WarmingActivityStatus.FAILED,
                    meta={"error": repr(exc)},
                )

        return execute

    return decorator
