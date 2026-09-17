from enum import Enum


class RiskLevel(str, Enum):
    """Уровень риска бана (Anti-Ban Predictor, этап 11)."""

    LOW = "low"           # 0.0–0.2
    MEDIUM = "medium"     # 0.2–0.5
    HIGH = "high"         # 0.5–0.8
    CRITICAL = "critical" # 0.8–1.0

    @classmethod
    def from_score(cls, risk: float) -> "RiskLevel":
        if risk >= 0.8:
            return cls.CRITICAL
        if risk >= 0.5:
            return cls.HIGH
        if risk >= 0.2:
            return cls.MEDIUM
        return cls.LOW
