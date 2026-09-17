from enum import Enum


class HealthEventType(str, Enum):
    """Типы health-инцидентов (PROJECT-STAGES §1.3, §5.3)."""

    FLOOD_WAIT = "flood_wait"
    SPAM_BLOCK = "spam_block"
    RESTRICTED = "restricted"
    PROXY_DOWN = "proxy_down"
    SESSION_REVOKED = "session_revoked"
    AUTH_FAILED = "auth_failed"


class PhoneStatus(str, Enum):
    """Итог активной проверки номера аккаунта."""

    UNKNOWN = "unknown"
    OK = "ok"
    BANNED = "banned"


class HealthCategory(str, Enum):
    """Категория состояния для UI (производная от score, не хранится)."""

    CRITICAL = "critical"  # 0
    RISKY = "risky"        # 1..40
    WARM = "warm"          # 41..70
    HEALTHY = "healthy"    # 71..100

    @classmethod
    def from_score(cls, score: int) -> "HealthCategory":
        if score <= 0:
            return cls.CRITICAL
        if score <= 40:
            return cls.RISKY
        if score <= 70:
            return cls.WARM
        return cls.HEALTHY
