"""Anti-Ban Predictor v1: rule-based risk scoring (этап 11).

Чистая функция от ``RiskFeatures`` → ``RiskPrediction``. Принцип тот же, что и
health_score.py: все побочки остаются вызывающему коду, здесь только математика.

Когда появится ML-модель, эта формула останется как fallback и baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.enums.risk import RiskLevel


# ── Feature weights ──────────────────────────────────────────────────────────

# Incident frequency (exponential scaling).
W_FLOOD_24H = 0.06
W_FLOOD_7D = 0.03
W_SPAM_BLOCK_7D = 0.25
W_SPAM_BLOCK_30D = 0.10

# Action health.
W_FAIL_RATE_24H = 0.20
W_FAIL_RATE_7D = 0.10
W_HIGH_INTENSITY = 0.08

# Protective factors (negative = reduces risk).
W_PROFILE_COMPLETE = -0.03  # per field (max -0.12)
W_AGE_BONUS = -0.05         # per bracket (see _age_factor)
W_ACTION_DIVERSITY = -0.04

# Unresolved incidents.
W_UNRESOLVED = 0.08  # per incident, capped

# Caps.
UNRESOLVED_CAP = 3
INTENSITY_THRESHOLD = 15  # actions/hour that signals suspicious activity


@dataclass
class RiskFeatures:
    """All features the predictor needs. Extracted from existing DB tables."""

    flood_waits_24h: int = 0
    flood_waits_7d: int = 0
    spam_blocks_7d: int = 0
    spam_blocks_30d: int = 0
    action_fail_rate_24h: float = 0.0  # 0.0–1.0
    action_fail_rate_7d: float = 0.0
    actions_per_hour_24h: float = 0.0
    unique_action_types_7d: int = 0
    total_action_types: int = 7  # WarmingActionType count
    profile_completeness: int = 0  # 0–4 (2fa + username + avatar + bio)
    age_days: Optional[int] = None
    hours_since_last_incident: Optional[float] = None
    unresolved_incidents: int = 0
    session_alive: Optional[bool] = None
    phone_banned: bool = False
    current_health_score: int = 100


@dataclass
class RiskPrediction:
    """Prediction result with breakdown for transparency."""

    risk_score: float  # 0.0–1.0
    risk_level: RiskLevel
    contributions: list[tuple[str, float]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "risk_score": round(self.risk_score, 4),
            "risk_level": self.risk_level.value,
            "contributions": [
                {"factor": f, "contribution": round(c, 4)}
                for f, c in self.contributions
            ],
        }


def _age_factor(age_days: Optional[int]) -> float:
    """Older accounts get a risk reduction bonus."""
    if age_days is None:
        return 0.0
    if age_days >= 180:
        return 3.0  # max bonus
    if age_days >= 90:
        return 2.0
    if age_days >= 30:
        return 1.0
    if age_days >= 7:
        return 0.5
    return 0.0


def _diversity_factor(unique: int, total: int) -> float:
    """High action diversity reduces risk (looks more human)."""
    if total <= 0:
        return 0.0
    ratio = unique / total
    if ratio >= 0.7:
        return 1.0
    if ratio >= 0.4:
        return 0.5
    return 0.0


def predict_risk(features: RiskFeatures) -> RiskPrediction:
    """Compute ban risk from features. Returns 0.0–1.0 with breakdown."""

    contributions: list[tuple[str, float]] = []

    # Fatal: session dead or phone banned → risk = 1.0.
    if features.session_alive is False:
        return RiskPrediction(
            risk_score=1.0,
            risk_level=RiskLevel.CRITICAL,
            contributions=[("session_dead", 1.0)],
        )
    if features.phone_banned:
        return RiskPrediction(
            risk_score=1.0,
            risk_level=RiskLevel.CRITICAL,
            contributions=[("phone_banned", 1.0)],
        )

    risk = 0.0

    # Flood waits (exponential: each successive one hurts more).
    if features.flood_waits_24h > 0:
        c = W_FLOOD_24H * (features.flood_waits_24h ** 1.5)
        contributions.append(("flood_waits_24h", c))
        risk += c
    if features.flood_waits_7d > 0:
        c = W_FLOOD_7D * (features.flood_waits_7d ** 1.3)
        contributions.append(("flood_waits_7d", c))
        risk += c

    # Spam blocks (most dangerous signal).
    if features.spam_blocks_7d > 0:
        c = W_SPAM_BLOCK_7D * features.spam_blocks_7d
        contributions.append(("spam_blocks_7d", c))
        risk += c
    if features.spam_blocks_30d > 0:
        c = W_SPAM_BLOCK_30D * features.spam_blocks_30d
        contributions.append(("spam_blocks_30d", c))
        risk += c

    # Action fail rate.
    if features.action_fail_rate_24h > 0:
        c = W_FAIL_RATE_24H * features.action_fail_rate_24h
        contributions.append(("action_fail_rate_24h", c))
        risk += c
    if features.action_fail_rate_7d > 0:
        c = W_FAIL_RATE_7D * features.action_fail_rate_7d
        contributions.append(("action_fail_rate_7d", c))
        risk += c

    # High intensity.
    if features.actions_per_hour_24h > INTENSITY_THRESHOLD:
        c = W_HIGH_INTENSITY * (features.actions_per_hour_24h / INTENSITY_THRESHOLD - 1)
        contributions.append(("high_intensity", c))
        risk += c

    # Unresolved incidents.
    if features.unresolved_incidents > 0:
        capped = min(features.unresolved_incidents, UNRESOLVED_CAP)
        c = W_UNRESOLVED * capped
        contributions.append(("unresolved_incidents", c))
        risk += c

    # Protective: profile completeness.
    if features.profile_completeness > 0:
        c = W_PROFILE_COMPLETE * features.profile_completeness
        contributions.append(("profile_completeness", c))
        risk += c

    # Protective: account age.
    age_f = _age_factor(features.age_days)
    if age_f > 0:
        c = W_AGE_BONUS * age_f
        contributions.append(("age_bonus", c))
        risk += c

    # Protective: action diversity.
    div_f = _diversity_factor(
        features.unique_action_types_7d, features.total_action_types
    )
    if div_f > 0:
        c = W_ACTION_DIVERSITY * div_f
        contributions.append(("action_diversity", c))
        risk += c

    # Clamp to [0.0, 1.0].
    risk = max(0.0, min(1.0, risk))

    return RiskPrediction(
        risk_score=risk,
        risk_level=RiskLevel.from_score(risk),
        contributions=contributions,
    )
