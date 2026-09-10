from enum import Enum


class Initiator(str, Enum):
    """Инициатор перехода стадии (PROJECT-STAGES §1.2)."""

    USER = "user"
    AUTO = "auto"
    HEALTH = "health"
