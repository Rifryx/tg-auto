"""Общий каркас действий прогрева: результат и обёртка try/except."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Union

from core.enums import WarmingActionType, WarmingActivityStatus
from core.models import Account
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

    Ни одно сетевое исключение Telethon не пробрасывается наружу — действие
    прогрева не должно ронять tick; неуспех фиксируется как ``status=failed``.
    """

    def decorator(body: _ActionBody):
        async def execute(client, account: Account) -> WarmingActionResult:
            try:
                target = await body(client, account)
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
