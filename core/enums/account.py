from enum import Enum


class AccountStatus(str, Enum):
    """Стадии жизненного цикла аккаунта (PROJECT-STAGES §1.1)."""

    CREATED = "created"
    WARMING = "warming"
    POOL = "pool"
    ASSIGNED = "assigned"
    COOLDOWN = "cooldown"
    RETIRED = "retired"
    BANNED = "banned"


class WarmingProfile(str, Enum):
    """Пресеты интенсивности прогрева (PROJECT-STAGES §1.3, §5.2)."""

    MINIMAL = "minimal"
    MEDIUM = "medium"
    DENSE = "dense"
