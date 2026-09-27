"""Промпт 2.1: TriggerRunner.

Mock'аем TelegramClient (callable + get_input_entity) и Governor. Проверяем
все ветки: happy path, FLOOD_WAIT (Telethon и governor-self-throttle),
privacy, deleted, username not found, невалидный peer.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Telethon — обязательный runtime-dep проекта (см. pyproject.toml). В окружениях
# без него (например, локальный dev без установленных worker-зависимостей)
# просто скипаем весь файл — в CI Telethon стоит и тесты идут.
telethon = pytest.importorskip("telethon")
from telethon.errors import (  # noqa: E402
    FloodWaitError,
    PeerIdInvalidError,
    UserDeactivatedError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)

from modules.priming.schemas.enums import ExecutionOutcome, TriggerAction
from modules.priming.worker.trigger import (
    GOVERNOR_ACTION_TYPE,
    TargetRef,
    TriggerRunner,
)


pytestmark = pytest.mark.asyncio


def _make_client(*, resolve=None, call_side_effect=None):
    """Собирает mock TelegramClient: он и awaitable, и умеет get_input_entity."""
    client = MagicMock(name="TelegramClient")
    client.get_input_entity = AsyncMock(
        return_value=resolve if resolve is not None else object()
    )
    if call_side_effect is not None:
        client.side_effect = call_side_effect
    else:
        # `client(request)` — awaitable, возвращающий пустышку.
        async def _ok(*_a, **_k):
            return SimpleNamespace(ok=True)
        client.side_effect = _ok
    return client


def _make_governor(*, allow: bool = True):
    gov = MagicMock(name="Governor")
    gov.check_and_reserve = AsyncMock(return_value=allow)
    return gov


def _clock():
    """Детерминированные часы: 0.000 → 0.123 с (латентность 123 мс)."""
    values = iter([0.0, 0.123])
    return lambda: next(values)


# ---------------------------------------------------------------------------
# TargetRef
# ---------------------------------------------------------------------------

def test_target_ref_prefers_tg_user_id() -> None:
    t = TargetRef(tg_user_id=42, username="ignored")
    assert t.as_peer() == 42


def test_target_ref_username_prefixed() -> None:
    assert TargetRef(username="alice").as_peer() == "@alice"
    assert TargetRef(username="@alice").as_peer() == "@alice"


def test_target_ref_empty_raises() -> None:
    with pytest.raises(ValueError):
        TargetRef().as_peer()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_run_secret_chat_returns_primed() -> None:
    client = _make_client()
    gov = _make_governor()
    runner = TriggerRunner(
        client, gov, account_id=42,
        clock=_clock(),
        random_bytes=lambda n: b"\x00" * n,
    )

    result = await runner.run(
        TriggerAction.SECRET_CHAT_REQUEST, TargetRef(username="alice"),
    )

    assert result.outcome is ExecutionOutcome.PRIMED
    assert result.latency_ms == 123
    assert result.error_code is None
    # Governor вызван ровно с типом "priming".
    gov.check_and_reserve.assert_awaited_once_with(42, GOVERNOR_ACTION_TYPE)
    # Один вызов get_input_entity + один MTProto-запрос.
    client.get_input_entity.assert_awaited_once()


async def test_run_set_ttl_1d_calls_mtproto() -> None:
    client = _make_client()
    gov = _make_governor()
    runner = TriggerRunner(client, gov, account_id=1)
    result = await runner.run(TriggerAction.SET_TTL_1D, TargetRef(tg_user_id=10))
    assert result.outcome is ExecutionOutcome.PRIMED
    assert result.meta.get("period") == 86_400


# ---------------------------------------------------------------------------
# FLOOD_WAIT — Telethon
# ---------------------------------------------------------------------------

async def test_run_flood_wait_maps_seconds() -> None:
    async def _flood(*_a, **_k):
        raise FloodWaitError(request=None, capture=42)

    client = _make_client(call_side_effect=_flood)
    gov = _make_governor()
    runner = TriggerRunner(client, gov, account_id=1)
    result = await runner.run(
        TriggerAction.SECRET_CHAT_REQUEST, TargetRef(tg_user_id=10),
    )
    assert result.outcome is ExecutionOutcome.FLOOD_WAIT
    assert result.flood_wait_sec == 42
    assert result.error_code == "FloodWaitError"


# ---------------------------------------------------------------------------
# FLOOD_WAIT — self-throttle через governor
# ---------------------------------------------------------------------------

async def test_governor_rejection_produces_flood_wait_without_mtproto() -> None:
    client = _make_client()
    gov = _make_governor(allow=False)
    runner = TriggerRunner(client, gov, account_id=1)
    result = await runner.run(
        TriggerAction.SECRET_CHAT_REQUEST, TargetRef(username="a"),
    )
    assert result.outcome is ExecutionOutcome.FLOOD_WAIT
    assert result.error_code == "governor_reserved_out"
    assert result.flood_wait_sec is None
    # Ни один Telethon-вызов не должен уйти при отказе governor'а.
    client.get_input_entity.assert_not_awaited()


# ---------------------------------------------------------------------------
# Категоризация RPC-ошибок
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raise_exc, expected",
    [
        (
            lambda: UserPrivacyRestrictedError(request=None),
            ExecutionOutcome.PRIVACY_RESTRICTED,
        ),
        (
            lambda: UserDeactivatedError(request=None),
            ExecutionOutcome.DELETED,
        ),
        (
            lambda: UsernameNotOccupiedError(request=None),
            ExecutionOutcome.NOT_FOUND,
        ),
    ],
)
async def test_error_mapping(raise_exc, expected) -> None:
    async def _fail(*_a, **_k):
        raise raise_exc()

    client = _make_client(call_side_effect=_fail)
    gov = _make_governor()
    runner = TriggerRunner(client, gov, account_id=1)
    result = await runner.run(
        TriggerAction.SECRET_CHAT_REQUEST, TargetRef(username="a"),
    )
    assert result.outcome is expected


async def test_resolve_peer_failure_produces_not_found() -> None:
    client = _make_client()
    client.get_input_entity = AsyncMock(
        side_effect=PeerIdInvalidError(request=None)
    )
    gov = _make_governor()
    runner = TriggerRunner(client, gov, account_id=1)
    result = await runner.run(
        TriggerAction.SECRET_CHAT_REQUEST, TargetRef(username="missing"),
    )
    assert result.outcome is ExecutionOutcome.NOT_FOUND
    # MTProto-вызов не отправлен, если peer не резолвнулся.
    client.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown / not-implemented action → INTERNAL_ERROR
# ---------------------------------------------------------------------------

async def test_unhandled_action_returns_internal_error() -> None:
    client = _make_client()
    gov = _make_governor()
    runner = TriggerRunner(client, gov, account_id=1)
    # PINNED_MESSAGE_PING нет в _handlers на MVP.
    result = await runner.run(
        TriggerAction.PINNED_MESSAGE_PING, TargetRef(username="a"),
    )
    assert result.outcome is ExecutionOutcome.INTERNAL_ERROR
    assert result.error_code and result.error_code.startswith("unknown_action:")
