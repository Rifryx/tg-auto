"""Промпт 1.6: Pydantic Create/Read/Update модуля прайминга.

Основной фокус — граничная валидация из спеки §4 (диапазоны задержек,
лимитов, privacy_rate, идентичности цели).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from modules.priming.schemas import (
    AnchorChannelCreate,
    HumanizerMode,
    ParserRunRequest,
    ParserSourceKind,
    PrimingCampaignCreate,
    PrimingCampaignRead,
    PrimingCampaignUpdate,
    PrimingTargetCreate,
    PrimingTargetImport,
    TriggerAction,
    WarmupProfile,
)


# ---------------------------------------------------------------------------
# PrimingCampaignCreate / Update
# ---------------------------------------------------------------------------

def _minimal_campaign_kwargs() -> dict:
    return {
        "name": "Test",
        "trigger_action": TriggerAction.SECRET_CHAT_REQUEST,
    }


def test_campaign_create_minimal_defaults() -> None:
    c = PrimingCampaignCreate(**_minimal_campaign_kwargs())
    assert c.humanizer_mode is HumanizerMode.BALANCED
    assert c.warmup_profile is WarmupProfile.WARM
    assert c.delay_between_targets_sec_min == 60
    assert c.delay_between_targets_sec_max == 180
    assert c.daily_limit_per_account == 35
    assert c.stop_on_privacy_rate == 0.3


def test_campaign_delay_range_ordered() -> None:
    with pytest.raises(ValidationError):
        PrimingCampaignCreate(
            **_minimal_campaign_kwargs(),
            delay_between_targets_sec_min=120,
            delay_between_targets_sec_max=60,
        )


def test_campaign_daily_limit_bounds() -> None:
    with pytest.raises(ValidationError):
        PrimingCampaignCreate(**_minimal_campaign_kwargs(), daily_limit_per_account=0)
    with pytest.raises(ValidationError):
        PrimingCampaignCreate(**_minimal_campaign_kwargs(), daily_limit_per_account=501)


def test_campaign_privacy_rate_bounds() -> None:
    with pytest.raises(ValidationError):
        PrimingCampaignCreate(**_minimal_campaign_kwargs(), stop_on_privacy_rate=-0.01)
    with pytest.raises(ValidationError):
        PrimingCampaignCreate(**_minimal_campaign_kwargs(), stop_on_privacy_rate=1.01)


def test_campaign_flood_wait_pause_positive() -> None:
    with pytest.raises(ValidationError):
        PrimingCampaignCreate(**_minimal_campaign_kwargs(), flood_wait_pause_sec=0)


def test_campaign_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        PrimingCampaignCreate(
            **_minimal_campaign_kwargs(), unknown_field=1,  # type: ignore[call-arg]
        )


def test_campaign_update_all_fields_optional() -> None:
    # Пустой Update — валиден (partial-обновление).
    upd = PrimingCampaignUpdate()
    assert upd.name is None


def test_campaign_update_delay_range_ordered() -> None:
    with pytest.raises(ValidationError):
        PrimingCampaignUpdate(
            delay_between_targets_sec_min=200,
            delay_between_targets_sec_max=100,
        )


def test_campaign_read_from_orm() -> None:
    """Read.from_attributes = True: строится из ORM-объекта."""
    from types import SimpleNamespace

    now = datetime.now(timezone.utc)
    orm_like = SimpleNamespace(
        id=1, name="c",
        mode="priming", trigger_action="secret_chat_request",
        humanizer_mode="balanced",
        delay_between_targets_sec_min=60, delay_between_targets_sec_max=180,
        flood_wait_pause_sec=500, max_flood_waits_per_account=3,
        daily_limit_per_account=35, warmup_profile="warm",
        require_username=True, premium_only=False,
        exclude_bots=True, exclude_deleted=True, exclude_admins=True,
        stop_on_privacy_rate=0.3, status="draft",
        started_at=None, finished_at=None, created_by=None,
        created_at=now, updated_at=now, counters=None,
    )
    read = PrimingCampaignRead.model_validate(orm_like)
    assert read.id == 1


# ---------------------------------------------------------------------------
# PrimingTargetCreate / Import
# ---------------------------------------------------------------------------

def test_target_requires_identity() -> None:
    with pytest.raises(ValidationError):
        PrimingTargetCreate()


def test_target_accepts_any_identity_field() -> None:
    assert PrimingTargetCreate(tg_user_id=1).tg_user_id == 1
    assert PrimingTargetCreate(username="alice").username == "alice"
    assert PrimingTargetCreate(phone="+79001234567").phone == "+79001234567"


def test_target_tg_user_id_positive() -> None:
    with pytest.raises(ValidationError):
        PrimingTargetCreate(tg_user_id=0)


def test_target_import_min_length() -> None:
    with pytest.raises(ValidationError):
        PrimingTargetImport(targets=[])


# ---------------------------------------------------------------------------
# AnchorChannel
# ---------------------------------------------------------------------------

def test_anchor_channel_title_required() -> None:
    with pytest.raises(ValidationError):
        AnchorChannelCreate(account_id=1, channel_tg_id=10, title="")


# ---------------------------------------------------------------------------
# ParserRunRequest
# ---------------------------------------------------------------------------

def test_parser_run_request_kind_enum() -> None:
    req = ParserRunRequest(
        kind=ParserSourceKind.CHAT_MESSAGES,
        params={"chat_ref": "@x", "days_window": 7, "min_messages": 3},
    )
    assert req.kind is ParserSourceKind.CHAT_MESSAGES
