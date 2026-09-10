from enum import Enum


class HealthEventType(str, Enum):
    """Типы health-инцидентов (PROJECT-STAGES §1.3, §5.3)."""

    FLOOD_WAIT = "flood_wait"
    SPAM_BLOCK = "spam_block"
    RESTRICTED = "restricted"
    PROXY_DOWN = "proxy_down"
    SESSION_REVOKED = "session_revoked"
    AUTH_FAILED = "auth_failed"
