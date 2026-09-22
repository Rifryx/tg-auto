from enum import Enum


class WarmingActivityKind(str, Enum):
    """Вид прогрева: первичный или поддерживающий (PROJECT-STAGES §1.3)."""

    INITIAL = "initial"
    MAINTENANCE = "maintenance"


class WarmingActionType(str, Enum):
    """Тип действия прогрева (PROJECT-STAGES §1.3)."""

    SUBSCRIBE_CHANNEL = "subscribe_channel"
    READ_HISTORY = "read_history"
    REACTION = "reaction"
    VIEW_MEDIA = "view_media"
    JOIN_GROUP = "join_group"
    IDLE_ONLINE = "idle_online"
    UPDATE_PROFILE = "update_profile"
    # Trust-graph (этап 10, backlog #2): «естественное» взаимодействие между
    # аккаунтами одного проекта/персоны/кампании — читаем историю peer'а или
    # ставим реакцию на его пост.
    INTERACT_WITH_PEER = "interact_with_peer"


class WarmingActivityStatus(str, Enum):
    """Результат действия прогрева (PROJECT-STAGES §1.3)."""

    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
