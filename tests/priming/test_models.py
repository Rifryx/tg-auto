"""Промпт 1.3: ORM-модели кампании / аккаунтов / целей.

Тесты metadata-уровня: без реальной БД. Проверяем таблицы, колонки,
FK/UNIQUE/CHECK и индексы. Живой ``alembic upgrade head`` покрывается
общим conftest'ом при доступной postgres_test.
"""

from __future__ import annotations

from core.models.base import PRIMING_SCHEMA
from modules.priming.models import (
    PrimingCampaign,
    PrimingCampaignAccount,
    PrimingCampaignTarget,
)


# ---------------------------------------------------------------------------
# Схема и tablename'ы
# ---------------------------------------------------------------------------

def test_all_tables_in_priming_schema() -> None:
    for cls in (PrimingCampaign, PrimingCampaignAccount, PrimingCampaignTarget):
        assert cls.__table__.schema == PRIMING_SCHEMA, cls


def test_table_names() -> None:
    assert PrimingCampaign.__tablename__ == "campaigns"
    assert PrimingCampaignAccount.__tablename__ == "campaign_accounts"
    assert PrimingCampaignTarget.__tablename__ == "campaign_targets"


# ---------------------------------------------------------------------------
# Кампания
# ---------------------------------------------------------------------------

CAMPAIGN_REQUIRED_COLUMNS = {
    "id", "name", "mode", "trigger_action", "humanizer_mode",
    "delay_between_targets_sec_min", "delay_between_targets_sec_max",
    "flood_wait_pause_sec", "max_flood_waits_per_account",
    "daily_limit_per_account", "warmup_profile",
    "require_username", "premium_only", "exclude_bots", "exclude_deleted",
    "exclude_admins", "stop_on_privacy_rate",
    "status", "started_at", "finished_at", "created_by",
    "created_at", "updated_at",
}


def test_campaign_columns() -> None:
    columns = {c.name for c in PrimingCampaign.__table__.columns}
    assert CAMPAIGN_REQUIRED_COLUMNS.issubset(columns)


def test_campaign_status_default_and_checks() -> None:
    status = PrimingCampaign.__table__.c.status
    assert status.server_default is not None
    check_names = {
        c.name for c in PrimingCampaign.__table__.constraints if c.name
    }
    for expected in (
        "ck_campaigns_status_allowed",
        "ck_campaigns_mode_allowed",
        "ck_campaigns_trigger_action_allowed",
        "ck_campaigns_humanizer_mode_allowed",
        "ck_campaigns_warmup_profile_allowed",
        "ck_campaigns_delay_range_valid",
        "ck_campaigns_flood_wait_pause_valid",
        "ck_campaigns_max_flood_waits_valid",
        "ck_campaigns_daily_limit_valid",
        "ck_campaigns_stop_on_privacy_rate_valid",
    ):
        assert expected in check_names, expected


# ---------------------------------------------------------------------------
# Аккаунты кампании
# ---------------------------------------------------------------------------

def _fk_map(table) -> dict[str, tuple[str, str]]:
    """Возвращает: локальная колонка → (target_table, ondelete)."""
    out: dict[str, tuple[str, str]] = {}
    for fk in table.foreign_keys:
        out[fk.parent.name] = (
            fk.column.table.fullname,
            fk.ondelete or "",
        )
    return out


def test_campaign_account_has_correct_fks() -> None:
    fks = _fk_map(PrimingCampaignAccount.__table__)
    assert fks["campaign_id"] == (f"{PRIMING_SCHEMA}.campaigns", "CASCADE")
    assert fks["account_id"] == ("accounts", "CASCADE")


def test_campaign_account_unique_pair() -> None:
    uniques = [
        c for c in PrimingCampaignAccount.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    named = {u.name for u in uniques}
    assert "uq_campaign_accounts_campaign_id_account_id" in named


def test_campaign_account_profile_preset_column_has_no_fk_yet() -> None:
    """FK на priming.profile_presets появится в миграции 0041 (промпт 1.4)."""
    col = PrimingCampaignAccount.__table__.c.profile_preset_id
    assert col.nullable is True
    assert list(col.foreign_keys) == []


def test_campaign_account_state_default() -> None:
    default = PrimingCampaignAccount.__table__.c.state.server_default
    assert default is not None
    assert "idle" in str(default.arg)


# ---------------------------------------------------------------------------
# Цели кампании
# ---------------------------------------------------------------------------

def test_campaign_target_has_correct_fks() -> None:
    fks = _fk_map(PrimingCampaignTarget.__table__)
    assert fks["campaign_id"] == (f"{PRIMING_SCHEMA}.campaigns", "CASCADE")
    assert fks["assigned_account_id"] == ("accounts", "SET NULL")


def test_campaign_target_source_column_has_no_fk_yet() -> None:
    """FK на priming.target_sources появится в миграции 0041 (промпт 1.4)."""
    col = PrimingCampaignTarget.__table__.c.source_id
    assert col.nullable is True
    assert list(col.foreign_keys) == []


def test_campaign_target_identity_required_check() -> None:
    checks = {
        c.name for c in PrimingCampaignTarget.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint" and c.name
    }
    assert "ck_campaign_targets_identity_present" in checks
    assert "ck_campaign_targets_status_allowed" in checks
    assert "ck_campaign_targets_last_seen_bucket_allowed" in checks


def test_campaign_target_has_orchestrator_indexes() -> None:
    idx_names = {i.name for i in PrimingCampaignTarget.__table__.indexes}
    assert "ix_campaign_targets_campaign_status" in idx_names
    assert "ix_campaign_targets_campaign_tg_user" in idx_names


# ---------------------------------------------------------------------------
# Реэкспорт в core.models
# ---------------------------------------------------------------------------

def test_reexport_in_core_models() -> None:
    from core import models

    assert models.PrimingCampaign is PrimingCampaign
    assert models.PrimingCampaignAccount is PrimingCampaignAccount
    assert models.PrimingCampaignTarget is PrimingCampaignTarget
    assert models.PRIMING_SCHEMA == "priming"
