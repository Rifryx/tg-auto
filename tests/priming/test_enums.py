"""Промпт 1.2: enum'ы и общие Pydantic-схемы модуля прайминга.

Проверяем:
- значения enum'ов совпадают со спецификацией (spec §4, §5);
- переходы TargetStatus контролируются и терминальные состояния — тупики;
- Pagination / TimeRange корректно валидируются.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules.priming.schemas import (
    ErrorEnvelope,
    ExecutionOutcome,
    HumanizerMode,
    Pagination,
    ParserSourceKind,
    PrimingAccountState,
    PrimingCampaignStatus,
    TargetStatus,
    TimeRange,
    TriggerAction,
    WarmupProfile,
    all_enums,
    can_target_status_transition,
    target_status_allowed_transitions,
)


# ---------------------------------------------------------------------------
# Значения enum'ов
# ---------------------------------------------------------------------------

def test_campaign_status_values() -> None:
    assert {s.value for s in PrimingCampaignStatus} == {
        "draft", "queued", "running", "paused", "stopped", "finished", "failed",
    }


def test_trigger_action_values_cover_rnd_candidates() -> None:
    # Каждый action из R&D-реестра (scripts/priming_rnd/actions.py) должен
    # присутствовать в TriggerAction. Список продублирован здесь, чтобы
    # тест не зависел от импорта Telethon-heavy R&D-скрипта.
    rnd_candidates = {
        "set_ttl_1d",
        "set_ttl_off",
        "secret_chat_request",
        "contact_added",
        "contact_removed",
    }
    enum_values = {a.value for a in TriggerAction}
    missing = rnd_candidates - enum_values
    assert not missing, f"R&D candidates missing from TriggerAction: {missing}"


def test_humanizer_modes() -> None:
    assert {m.value for m in HumanizerMode} == {"off", "balanced", "aggressive"}


def test_warmup_profiles() -> None:
    assert {p.value for p in WarmupProfile} == {"cold", "warm", "hot"}


def test_account_state_values() -> None:
    assert {s.value for s in PrimingAccountState} == {
        "idle", "working", "cooldown", "quarantined", "disabled",
    }


def test_parser_source_kind_values() -> None:
    assert {k.value for k in ParserSourceKind} == {
        "chat_messages", "chat_members", "manual_list", "upload_csv",
    }


def test_execution_outcome_covers_spec_and_additions() -> None:
    values = {o.value for o in ExecutionOutcome}
    for v in (
        "primed", "flood_wait", "privacy_restricted", "deleted", "not_found",
        "channel_pinned_error", "internal_error",
    ):
        assert v in values
    # Добавленные позже (см. TriggerRunner + quiet-hours):
    assert "already_applied" in values
    assert "skipped_quiet" in values


def test_all_enums_registry_matches_module_symbols() -> None:
    names = {cls.__name__ for cls in all_enums()}
    # Спецификационные + вспомогательные; ровно те, что перечислены в реестре.
    assert names == {
        "PrimingCampaignStatus",
        "PrimingMode",
        "TriggerAction",
        "HumanizerMode",
        "WarmupProfile",
        "PrimingAccountState",
        "TargetStatus",
        "TargetLastSeen",
        "ExecutionOutcome",
        "ParserSourceKind",
        "BlacklistReason",
        "AnchorChannelState",
        "UsernameGenerator",
        "AvatarSource",
    }


# ---------------------------------------------------------------------------
# Переходы TargetStatus
# ---------------------------------------------------------------------------

def test_target_status_terminal_states_have_no_transitions() -> None:
    assert target_status_allowed_transitions(TargetStatus.PRIMED) == frozenset()
    assert target_status_allowed_transitions(TargetStatus.BLACKLISTED) == frozenset()


def test_target_status_primed_cannot_return_to_pending() -> None:
    """Пример из промпта: PRIMED → PENDING запрещён."""
    assert not can_target_status_transition(TargetStatus.PRIMED, TargetStatus.PENDING)


def test_target_status_happy_path() -> None:
    assert can_target_status_transition(TargetStatus.PENDING, TargetStatus.ASSIGNED)
    assert can_target_status_transition(TargetStatus.ASSIGNED, TargetStatus.PRIMED)


def test_target_status_re_release_on_worker_restart() -> None:
    # Worker падает после claim — цель должна вернуться в очередь.
    assert can_target_status_transition(TargetStatus.ASSIGNED, TargetStatus.PENDING)


def test_target_status_failed_can_retry_or_be_blacklisted() -> None:
    assert can_target_status_transition(TargetStatus.FAILED, TargetStatus.PENDING)
    assert can_target_status_transition(TargetStatus.FAILED, TargetStatus.BLACKLISTED)
    # Но не может «выздороветь» напрямую в PRIMED без нового прогона.
    assert not can_target_status_transition(TargetStatus.FAILED, TargetStatus.PRIMED)


def test_target_status_no_self_transition() -> None:
    for status in TargetStatus:
        assert not can_target_status_transition(status, status), (
            f"self-transition should be forbidden for {status}"
        )


# ---------------------------------------------------------------------------
# Общие Pydantic-схемы
# ---------------------------------------------------------------------------

def test_pagination_defaults_and_offset() -> None:
    p = Pagination()
    assert p.page == 1
    assert p.size == 20
    assert p.offset == 0
    assert p.limit == 20


def test_pagination_offset_arithmetic() -> None:
    p = Pagination(page=4, size=25)
    assert p.offset == 75
    assert p.limit == 25


def test_pagination_rejects_out_of_range() -> None:
    with pytest.raises(Exception):
        Pagination(page=0, size=20)
    with pytest.raises(Exception):
        Pagination(page=1, size=0)
    with pytest.raises(Exception):
        Pagination(page=1, size=201)


def test_time_range_allows_open_bounds() -> None:
    assert TimeRange().start is None
    assert TimeRange(start=datetime(2026, 1, 1, tzinfo=timezone.utc)).end is None


def test_time_range_rejects_inverted() -> None:
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    end = start - timedelta(days=1)
    with pytest.raises(Exception):
        TimeRange(start=start, end=end)


def test_error_envelope_shape() -> None:
    e = ErrorEnvelope(error="target_not_found", message="Target does not exist")
    assert e.error == "target_not_found"
    assert e.details is None
    # extra="forbid": незнакомое поле роняет валидацию.
    with pytest.raises(Exception):
        ErrorEnvelope(error="x", message="y", unknown=1)  # type: ignore[call-arg]
