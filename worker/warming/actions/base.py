"""Общий каркас действий прогрева: результат и обёртка try/except."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, Union

from core.enums import WarmingActionType, WarmingActivityStatus
from core.models import Account, Persona
from worker.tasks.logging import get_logger

# Небольшой пул публичных целей для действий прогрева (реестра интересов пока
# нет — берём общеизвестные публичные каналы/группы).
DISCOVERY_CHANNELS = ("telegram", "durov", "tginfo")
DISCOVERY_GROUPS = ("python", "telegramdesktop")


def pick_target(
    rng: random.Random,
    persona: Optional[Persona],
    kind: str,
    fallback: tuple[str, ...],
) -> str:
    """Выбрать target для warming action (этап 10, backlog #1).

    Если у аккаунта есть persona с непустым ``interests`` — берём случайный
    оттуда. Fallback на глобальную константу (общие DISCOVERY_CHANNELS/GROUPS).

    ``kind`` — для будущей типизации (channel/group/…); пока только логгируем.
    """
    if persona is not None and persona.interests:
        return rng.choice(list(persona.interests))
    return rng.choice(fallback)


@dataclass
class WarmingActionResult:
    action_type: WarmingActionType
    status: WarmingActivityStatus
    target: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


# Категории ошибок warming action (этап 10, backlog #3).
# ``ephemeral`` — «повторим позже/на другой цели», не бракуем аккаунт.
# ``target_broken`` — цель конкретно, не аккаунт: cannot subscribe/write.
# ``rate_limit`` — flood-wait/Rate-limit, ждать.
# ``fatal`` — session dead/phone banned, обычно уже поймал health-монитор.
# ``unknown`` — всё прочее (для будущей категоризации).
_EPHEMERAL_ERRORS = {
    "ChatWriteForbiddenError",  # закрытый канал: попробуем другой в след. tick
    "ChannelPrivateError",       # приватный/удалённый — аналогично
    "ChatAdminRequiredError",    # нет прав — не наша проблема
    "UsernameInvalidError",
    "UsernameNotOccupiedError",
    "PeerIdInvalidError",
    "InviteHashExpiredError",
    "InviteHashInvalidError",
    "ChannelsTooMuchError",      # аккаунт достиг лимита каналов — тарг не тот
}
_RATE_LIMIT_ERRORS = {
    "FloodWaitError",
    "SlowModeWaitError",
}
_FATAL_ERRORS = {
    "AuthKeyUnregisteredError",
    "SessionRevokedError",
    "PhoneNumberBannedError",
    "UserDeactivatedError",
    "UserDeactivatedBanError",
}


def _categorize_error(exc: BaseException) -> str:
    name = type(exc).__name__
    if name in _EPHEMERAL_ERRORS:
        return "target_broken"
    if name in _RATE_LIMIT_ERRORS:
        return "rate_limit"
    if name in _FATAL_ERRORS:
        return "fatal"
    return "unknown"


# Тело действия возвращает target (str), (target, meta) или None; обёртка ловит
# исключения и распаковывает результат через _split_result.
_ActionBody = Callable[..., Awaitable[Union[str, tuple, None]]]


def _split_result(raw: Any) -> tuple[Optional[str], Optional[dict]]:
    """Разбирает возврат тела действия в (target, meta)."""
    if isinstance(raw, tuple):
        target = raw[0] if len(raw) > 0 else None
        meta = raw[1] if len(raw) > 1 else None
        target = str(target) if target is not None else None
        meta = dict(meta) if isinstance(meta, dict) else None
        return target, meta
    if raw is None:
        return None, None
    return str(raw), None


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
            persona: Optional[Persona] = None,
            rng: Optional[random.Random] = None,
        ) -> WarmingActionResult:
            # Ленивый импорт: worker.health → worker.tasks.logging, а обратная
            # дуга (login/warming → worker.health) должна оставаться ленивой,
            # иначе цикл при импорте worker.health раньше worker.tasks.
            from worker.health import around_telethon_call

            # Тело принимает persona/rng/session_factory через **kwargs.
            # Actions, которым это не нужно, просто игнорируют через **_.
            call_kwargs = {
                "persona": persona,
                "rng": rng,
                "session_factory": session_factory,
            }

            try:
                if session_factory is None:
                    # Без ctx (напр. прямой вызов в старых тестах) — без health-обёртки.
                    raw = await body(client, account, **call_kwargs)
                else:
                    raw = await around_telethon_call(
                        lambda: body(client, account, **call_kwargs),
                        account_id=account.id,
                        session_factory=session_factory,
                        publisher=publisher,
                        now=now,
                    )
                # Тело может вернуть target (str) или (target, meta) — meta хранит
                # детали действия (эмодзи реакции, кол-во просмотренных и т.п.).
                target, meta = _split_result(raw)
                return WarmingActionResult(
                    action_type, WarmingActivityStatus.DONE, target=target, meta=meta
                )
            except Exception as exc:  # noqa: BLE001 - действие изолировано
                category = _categorize_error(exc)
                get_logger().warning(
                    "warming.action_failed",
                    action=action_type.value,
                    account_id=account.id,
                    error=repr(exc),
                    category=category,
                )
                return WarmingActionResult(
                    action_type,
                    WarmingActivityStatus.FAILED,
                    meta={"error": repr(exc), "error_category": category},
                )

        return execute

    return decorator
