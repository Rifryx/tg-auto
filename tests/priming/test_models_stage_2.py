"""Промпт 1.4: остальные ORM-модели модуля прайминга.

Metadata-уровневые проверки для target_sources, profile_presets,
anchor_channels, execution_log, flood_incidents, blacklist.
Живой ``alembic upgrade head`` идёт через общий conftest.
"""

from __future__ import annotations

from core.models.base import PRIMING_SCHEMA
from modules.priming.models import (
    PrimingAnchorChannel,
    PrimingBlacklist,
    PrimingExecutionLog,
    PrimingFloodIncident,
    PrimingProfilePreset,
    PrimingTargetSource,
)


def _fk_map(table) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for fk in table.foreign_keys:
        out[fk.parent.name] = (fk.column.table.fullname, fk.ondelete or "")
    return out


def _check_names(table) -> set[str]:
    return {
        c.name for c in table.constraints
        if c.__class__.__name__ == "CheckConstraint" and c.name
    }


# --- target_sources ---------------------------------------------------------

def test_target_source_schema_and_fk() -> None:
    t = PrimingTargetSource.__table__
    assert t.schema == PRIMING_SCHEMA
    assert _fk_map(t)["campaign_id"] == (f"{PRIMING_SCHEMA}.campaigns", "CASCADE")


def test_target_source_checks() -> None:
    checks = _check_names(PrimingTargetSource.__table__)
    for expected in (
        "ck_target_sources_kind_allowed",
        "ck_target_sources_counts_valid",
        "ck_target_sources_days_window_valid",
        "ck_target_sources_min_messages_valid",
    ):
        assert expected in checks, expected


# --- profile_presets --------------------------------------------------------

def test_profile_preset_columns_and_defaults() -> None:
    cols = {c.name for c in PrimingProfilePreset.__table__.columns}
    for expected in (
        "owner_user_id", "name", "first_name_pool", "last_name_pool",
        "username_generator", "bio_text", "bio_link", "avatar_source",
        "stories_pool_id", "anchor_channel_template_id",
    ):
        assert expected in cols
    ug = PrimingProfilePreset.__table__.c.username_generator.server_default
    assert ug is not None and "llm" in str(ug.arg)
    av = PrimingProfilePreset.__table__.c.avatar_source.server_default
    assert av is not None and "upload" in str(av.arg)


def test_profile_preset_index_on_owner() -> None:
    idx_names = {i.name for i in PrimingProfilePreset.__table__.indexes}
    assert "ix_profile_presets_owner" in idx_names


def test_profile_preset_forward_refs_have_no_fk() -> None:
    # stories_pool_id / anchor_channel_template_id — FK будет добавлен на
    # этапе 4 (POC-визард).
    for col_name in ("stories_pool_id", "anchor_channel_template_id"):
        col = PrimingProfilePreset.__table__.c[col_name]
        assert col.nullable is True
        assert list(col.foreign_keys) == []


# --- anchor_channels --------------------------------------------------------

def test_anchor_channel_unique_per_account() -> None:
    uniques = {
        u.name for u in PrimingAnchorChannel.__table__.constraints
        if u.__class__.__name__ == "UniqueConstraint"
    }
    assert "uq_anchor_channels_account_id" in uniques


def test_anchor_channel_fk_and_check() -> None:
    fks = _fk_map(PrimingAnchorChannel.__table__)
    assert fks["account_id"] == ("accounts", "CASCADE")
    assert "ck_anchor_channels_state_allowed" in _check_names(
        PrimingAnchorChannel.__table__,
    )


# --- execution_log ----------------------------------------------------------

def test_execution_log_is_append_only() -> None:
    """Никакого updated_at — таблица append-only (см. модуль-docstring)."""
    cols = {c.name for c in PrimingExecutionLog.__table__.columns}
    assert "updated_at" not in cols
    assert "started_at" in cols and "finished_at" in cols


def test_execution_log_fks() -> None:
    fks = _fk_map(PrimingExecutionLog.__table__)
    assert fks["campaign_id"] == (f"{PRIMING_SCHEMA}.campaigns", "CASCADE")
    assert fks["account_id"] == ("accounts", "CASCADE")
    assert fks["target_id"] == (
        f"{PRIMING_SCHEMA}.campaign_targets", "CASCADE",
    )


def test_execution_log_indexes_for_logs_screen() -> None:
    idx_names = {i.name for i in PrimingExecutionLog.__table__.indexes}
    assert "ix_execution_log_campaign_started" in idx_names
    assert "ix_execution_log_campaign_outcome" in idx_names


# --- flood_incidents --------------------------------------------------------

def test_flood_incident_fk_and_index() -> None:
    fks = _fk_map(PrimingFloodIncident.__table__)
    assert fks["campaign_account_id"] == (
        f"{PRIMING_SCHEMA}.campaign_accounts", "CASCADE",
    )
    idx_names = {i.name for i in PrimingFloodIncident.__table__.indexes}
    assert "ix_flood_incidents_campaign_account_at" in idx_names


# --- blacklist --------------------------------------------------------------

def test_blacklist_allows_global_owner() -> None:
    col = PrimingBlacklist.__table__.c.owner_user_id
    assert col.nullable is True  # NULL = глобальный


def test_blacklist_identity_check_and_indexes() -> None:
    checks = _check_names(PrimingBlacklist.__table__)
    assert "ck_blacklist_reason_allowed" in checks
    assert "ck_blacklist_identity_present" in checks
    idx_names = {i.name for i in PrimingBlacklist.__table__.indexes}
    for expected in (
        "ix_blacklist_owner_tg_user_id",
        "ix_blacklist_owner_username",
        "ix_blacklist_owner_phone",
    ):
        assert expected in idx_names, expected


# --- реэкспорт --------------------------------------------------------------

def test_core_models_reexports_everything() -> None:
    from core import models

    for cls in (
        PrimingAnchorChannel, PrimingBlacklist, PrimingExecutionLog,
        PrimingFloodIncident, PrimingProfilePreset, PrimingTargetSource,
    ):
        assert getattr(models, cls.__name__) is cls
