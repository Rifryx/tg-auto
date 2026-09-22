from enum import Enum


class Initiator(str, Enum):
    """Инициатор перехода стадии (PROJECT-STAGES §1.2)."""

    USER = "user"
    AUTO = "auto"
    HEALTH = "health"


class TriggeredStatusChange(str, Enum):
    """Значения ``health_events.triggered_status_change`` (backlog #прочее).

    Health-инцидент может дёргать state machine — целевой статус фиксируется
    здесь для последующей аналитики. NULL в БД означает «статус не менялся».
    """

    COOLDOWN = "cooldown"
    BANNED = "banned"
    RETIRED = "retired"
