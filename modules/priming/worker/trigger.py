"""TriggerRunner — обёртка над MTProto-действиями прайминга (spec §5, промпт 2.1).

Задача: вызвать один ``TriggerAction`` для одной цели, поймать и
категоризовать Telethon-ошибки, вернуть :class:`TriggerResult` **без**
проброса исключений (кроме программных ошибок вроде неизвестного action).

- Все вызовы обёрнуты в rate-limit governor (тип действия ``"priming"``).
  При отказе governor'а — outcome ``FLOOD_WAIT`` без реальных Telethon-
  вызовов и с ``flood_wait_sec=None`` (это self-throttling).
- Идемпотентность на уровне MVP: значения enum'а ``ALREADY_APPLIED`` и
  соответствующая ветка предусмотрены; конкретные проверки состояния
  цели (например, «TTL уже включён») навешиваются по мере R&D
  (см. ``docs/priming-triggers.md``).
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PeerIdInvalidError,
    RPCError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)
from telethon.tl.functions.contacts import (
    AddContactRequest,
    DeleteContactsRequest,
)
from telethon.tl.functions.messages import (
    RequestEncryptionRequest,
    SetHistoryTTLRequest,
)

from modules.priming.schemas.enums import ExecutionOutcome, TriggerAction


GOVERNOR_ACTION_TYPE = "priming"

# Распределение outcome'ов для dry-run режима (docs/priming-triggers.md).
# Порядок важен для детерминированного розыгрыша по кумулятивной сумме.
DRY_RUN_DISTRIBUTION: tuple[tuple[ExecutionOutcome, float], ...] = (
    (ExecutionOutcome.PRIMED, 0.78),
    (ExecutionOutcome.PRIVACY_RESTRICTED, 0.12),
    (ExecutionOutcome.FLOOD_WAIT, 0.08),
    (ExecutionOutcome.DELETED, 0.02),
)


def _draw_dry_run_outcome(rng: random.Random) -> ExecutionOutcome:
    """Розыгрыш outcome'а по распределению DRY_RUN_DISTRIBUTION."""
    dice = rng.random()
    cum = 0.0
    for outcome, weight in DRY_RUN_DISTRIBUTION:
        cum += weight
        if dice < cum:
            return outcome
    # Численный «хвост» — падает на последний, PRIMED-подобный.
    return DRY_RUN_DISTRIBUTION[0][0]


@dataclass
class TargetRef:
    """Идентификация цели. Хотя бы одно поле должно быть заполнено."""

    tg_user_id: Optional[int] = None
    username: Optional[str] = None
    phone: Optional[str] = None

    def as_peer(self) -> Any:
        """Возвращает peer-подходящий для ``client.get_input_entity()``.

        Приоритет: numeric id > username > phone. Форма — совместимая с
        R&D-скриптом (``scripts/priming_rnd``).
        """
        if self.tg_user_id is not None:
            return self.tg_user_id
        if self.username:
            return self.username if self.username.startswith("@") else f"@{self.username}"
        if self.phone:
            return self.phone
        raise ValueError("TargetRef is empty")


@dataclass
class TriggerResult:
    outcome: ExecutionOutcome
    latency_ms: int = 0
    flood_wait_sec: Optional[int] = None
    error_code: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)


# Категоризация RPC-ошибок → ExecutionOutcome. Ошибка, которой нет в
# словаре, попадает в INTERNAL_ERROR (см. ``_map_error``).
_ERROR_MAP: dict[type[RPCError], ExecutionOutcome] = {
    UserPrivacyRestrictedError: ExecutionOutcome.PRIVACY_RESTRICTED,
    UserDeactivatedError: ExecutionOutcome.DELETED,
    UserDeactivatedBanError: ExecutionOutcome.DELETED,
    UsernameNotOccupiedError: ExecutionOutcome.NOT_FOUND,
    UsernameInvalidError: ExecutionOutcome.NOT_FOUND,
    PeerIdInvalidError: ExecutionOutcome.NOT_FOUND,
}


def _map_error(exc: RPCError) -> ExecutionOutcome:
    for cls, outcome in _ERROR_MAP.items():
        if isinstance(exc, cls):
            return outcome
    return ExecutionOutcome.INTERNAL_ERROR


class TriggerRunner:
    """Вызывает MTProto-триггеры прайминга через :class:`TelegramClient`.

    Governor и clock инъектируются, чтобы тесты не зависели от Redis и
    системного времени.
    """

    def __init__(
        self,
        client: TelegramClient,
        governor: Any,
        *,
        account_id: int,
        clock: Callable[[], float] = time.monotonic,
        random_bytes: Callable[[int], bytes] = os.urandom,
        dry_run: bool = False,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._client = client
        self._governor = governor
        self._account_id = account_id
        self._clock = clock
        self._random_bytes = random_bytes
        self._dry_run = dry_run
        self._rng = rng or random.Random()

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    async def run(
        self, action: TriggerAction, target: TargetRef
    ) -> TriggerResult:
        started = self._clock()

        # 0. dry-run: разыгрываем outcome по распределению без Telethon-
        # вызовов, без governor'а и без резолва peer'а. Пометку
        # ``dry_run=True`` кладём в meta — executor использует её для
        # флага в execution_log.
        if self._dry_run:
            outcome = _draw_dry_run_outcome(self._rng)
            return _finalize(started, self._clock, TriggerResult(
                outcome=outcome,
                # FLOOD_WAIT в симуляции — синтетическая пауза 60 сек.
                flood_wait_sec=60 if outcome is ExecutionOutcome.FLOOD_WAIT else None,
                meta={"dry_run": True},
            ))

        # 1. Rate-limit governor.
        try:
            reserved = await self._governor.check_and_reserve(
                self._account_id, GOVERNOR_ACTION_TYPE
            )
        except Exception as exc:  # pragma: no cover — Redis-ошибку не глотаем
            return _finalize(started, self._clock, TriggerResult(
                outcome=ExecutionOutcome.INTERNAL_ERROR,
                error_code=f"governor:{type(exc).__name__}",
            ))
        if not reserved:
            # Self-throttling: не флудвейт от Telegram, а наш лимит.
            return _finalize(started, self._clock, TriggerResult(
                outcome=ExecutionOutcome.FLOOD_WAIT,
                error_code="governor_reserved_out",
            ))

        # 2. Резолвим peer один раз (общий шаг для всех action'ов).
        try:
            peer = await self._client.get_input_entity(target.as_peer())
        except RPCError as exc:
            return _finalize(started, self._clock, TriggerResult(
                outcome=_map_error(exc),
                error_code=type(exc).__name__,
            ))

        # 3. Выбираем метод по action.
        handler = self._handlers().get(action)
        if handler is None:
            return _finalize(started, self._clock, TriggerResult(
                outcome=ExecutionOutcome.INTERNAL_ERROR,
                error_code=f"unknown_action:{action}",
            ))

        # 4. Выполняем и категоризуем Telethon-ошибки.
        try:
            meta = await handler(peer) or {}
        except FloodWaitError as exc:
            return _finalize(started, self._clock, TriggerResult(
                outcome=ExecutionOutcome.FLOOD_WAIT,
                flood_wait_sec=int(getattr(exc, "seconds", 0) or 0),
                error_code=type(exc).__name__,
            ))
        except RPCError as exc:
            return _finalize(started, self._clock, TriggerResult(
                outcome=_map_error(exc),
                error_code=type(exc).__name__,
            ))

        return _finalize(started, self._clock, TriggerResult(
            outcome=ExecutionOutcome.PRIMED,
            meta=meta,
        ))

    # --- реестр action'ов -------------------------------------------------
    def _handlers(self) -> dict[TriggerAction, Callable[..., Any]]:
        return {
            TriggerAction.SET_TTL_1D: self._run_set_ttl_1d,
            TriggerAction.SET_TTL_OFF: self._run_set_ttl_off,
            TriggerAction.SECRET_CHAT_REQUEST: self._run_secret_chat_request,
            TriggerAction.CONTACT_ADDED: self._run_contact_added,
            TriggerAction.CONTACT_REMOVED: self._run_contact_removed,
        }

    async def _run_set_ttl_1d(self, peer: Any) -> dict[str, Any]:
        await self._client(SetHistoryTTLRequest(peer=peer, period=86_400))
        return {"period": 86_400}

    async def _run_set_ttl_off(self, peer: Any) -> dict[str, Any]:
        await self._client(SetHistoryTTLRequest(peer=peer, period=0))
        return {"period": 0}

    async def _run_secret_chat_request(self, peer: Any) -> dict[str, Any]:
        random_id = int.from_bytes(self._random_bytes(8), "little", signed=True)
        g_a = self._random_bytes(256)
        await self._client(
            RequestEncryptionRequest(
                user_id=peer, random_id=random_id, g_a=g_a
            )
        )
        return {"random_id": random_id}

    async def _run_contact_added(self, peer: Any) -> dict[str, Any]:
        await self._client(
            AddContactRequest(
                id=peer,
                first_name="R",
                last_name="",
                phone="",
                add_phone_privacy_exception=True,
            )
        )
        return {}

    async def _run_contact_removed(self, peer: Any) -> dict[str, Any]:
        await self._client(DeleteContactsRequest(id=[peer]))
        return {}


def _finalize(
    started: float, clock: Callable[[], float], result: TriggerResult
) -> TriggerResult:
    result.latency_ms = int((clock() - started) * 1000)
    return result
