"""Юнит-тесты Anti-Ban Predictor (этап 11). Без БД, без сети.

Проверяют:
* fatal-условия (session_dead, phone_banned) → risk = 1.0
* инциденты (flood, spam) экспоненциально увеличивают risk
* profile completeness и age снижают risk
* action diversity — защитный фактор
* RiskLevel.from_score корректно маппит диапазоны
"""

from __future__ import annotations

from core.enums.risk import RiskLevel
from core.predictor import RiskFeatures, predict_risk


# ── fatal conditions ─────────────────────────────────────────────────────────


def test_session_dead_gives_max_risk():
    f = RiskFeatures(session_alive=False)
    p = predict_risk(f)
    assert p.risk_score == 1.0
    assert p.risk_level == RiskLevel.CRITICAL
    assert p.contributions[0][0] == "session_dead"


def test_phone_banned_gives_max_risk():
    f = RiskFeatures(phone_banned=True)
    p = predict_risk(f)
    assert p.risk_score == 1.0
    assert p.risk_level == RiskLevel.CRITICAL


# ── clean account → low risk ────────────────────────────────────────────────


def test_clean_account_low_risk():
    f = RiskFeatures(
        age_days=90,
        profile_completeness=4,
        unique_action_types_7d=5,
    )
    p = predict_risk(f)
    assert p.risk_score < 0.1
    assert p.risk_level == RiskLevel.LOW


# ── flood waits increase risk ───────────────────────────────────────────────


def test_flood_waits_increase_risk():
    base = predict_risk(RiskFeatures())
    with_floods = predict_risk(RiskFeatures(flood_waits_24h=3, flood_waits_7d=5))
    assert with_floods.risk_score > base.risk_score
    assert any(c[0] == "flood_waits_24h" for c in with_floods.contributions)


# ── spam blocks are the most dangerous signal ────────────────────────────────


def test_spam_blocks_high_risk():
    f = RiskFeatures(spam_blocks_7d=2, spam_blocks_30d=3)
    p = predict_risk(f)
    assert p.risk_score >= 0.5
    assert p.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


# ── fail rate increases risk ────────────────────────────────────────────────


def test_high_fail_rate_increases_risk():
    low_fail = predict_risk(RiskFeatures(action_fail_rate_24h=0.05))
    high_fail = predict_risk(RiskFeatures(action_fail_rate_24h=0.8))
    assert high_fail.risk_score > low_fail.risk_score


# ── protective factors ──────────────────────────────────────────────────────


def test_profile_completeness_reduces_risk():
    incomplete = predict_risk(RiskFeatures(
        flood_waits_24h=1, profile_completeness=0
    ))
    complete = predict_risk(RiskFeatures(
        flood_waits_24h=1, profile_completeness=4
    ))
    assert complete.risk_score < incomplete.risk_score


def test_account_age_reduces_risk():
    young = predict_risk(RiskFeatures(flood_waits_24h=1, age_days=2))
    old = predict_risk(RiskFeatures(flood_waits_24h=1, age_days=180))
    assert old.risk_score < young.risk_score


def test_action_diversity_reduces_risk():
    uniform = predict_risk(RiskFeatures(
        flood_waits_24h=1, unique_action_types_7d=1
    ))
    diverse = predict_risk(RiskFeatures(
        flood_waits_24h=1, unique_action_types_7d=6
    ))
    assert diverse.risk_score < uniform.risk_score


# ── unresolved incidents ────────────────────────────────────────────────────


def test_unresolved_incidents_add_risk():
    clean = predict_risk(RiskFeatures())
    with_incidents = predict_risk(RiskFeatures(unresolved_incidents=3))
    assert with_incidents.risk_score > clean.risk_score


def test_unresolved_incidents_capped():
    at_cap = predict_risk(RiskFeatures(unresolved_incidents=3))
    over_cap = predict_risk(RiskFeatures(unresolved_incidents=10))
    assert at_cap.risk_score == over_cap.risk_score


# ── high intensity ──────────────────────────────────────────────────────────


def test_high_intensity_increases_risk():
    normal = predict_risk(RiskFeatures(actions_per_hour_24h=5))
    intense = predict_risk(RiskFeatures(actions_per_hour_24h=30))
    assert intense.risk_score > normal.risk_score


# ── risk level mapping ──────────────────────────────────────────────────────


def test_risk_level_boundaries():
    assert RiskLevel.from_score(0.0) == RiskLevel.LOW
    assert RiskLevel.from_score(0.19) == RiskLevel.LOW
    assert RiskLevel.from_score(0.2) == RiskLevel.MEDIUM
    assert RiskLevel.from_score(0.49) == RiskLevel.MEDIUM
    assert RiskLevel.from_score(0.5) == RiskLevel.HIGH
    assert RiskLevel.from_score(0.79) == RiskLevel.HIGH
    assert RiskLevel.from_score(0.8) == RiskLevel.CRITICAL
    assert RiskLevel.from_score(1.0) == RiskLevel.CRITICAL


# ── risk score clamped ──────────────────────────────────────────────────────


def test_risk_never_exceeds_bounds():
    worst = predict_risk(RiskFeatures(
        flood_waits_24h=10,
        flood_waits_7d=50,
        spam_blocks_7d=5,
        spam_blocks_30d=10,
        action_fail_rate_24h=1.0,
        action_fail_rate_7d=1.0,
        actions_per_hour_24h=100,
        unresolved_incidents=10,
    ))
    assert 0.0 <= worst.risk_score <= 1.0

    best = predict_risk(RiskFeatures(
        age_days=365,
        profile_completeness=4,
        unique_action_types_7d=7,
    ))
    assert 0.0 <= best.risk_score <= 1.0


# ── as_dict roundtrip ──────────────────────────────────────────────────────


def test_as_dict_format():
    p = predict_risk(RiskFeatures(flood_waits_24h=2, age_days=30))
    d = p.as_dict()
    assert "risk_score" in d
    assert "risk_level" in d
    assert "contributions" in d
    assert isinstance(d["contributions"], list)
    for item in d["contributions"]:
        assert "factor" in item
        assert "contribution" in item
