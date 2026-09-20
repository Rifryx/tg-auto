from enum import Enum


class BulkJobStatus(str, Enum):
    """Общий статус bulk-задания."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"       # завершено, но есть провалившиеся item'ы
    CANCELLED = "cancelled"


class BulkItemStatus(str, Enum):
    """Статус одного элемента bulk-задания (по одному аккаунту)."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"    # напр., аккаунт в banned/retired — не берём
    CANCELLED = "cancelled"


class BulkActionType(str, Enum):
    """Реестр допустимых bulk-действий (этап 5 УТП).

    Дополнять здесь + регистрировать хендлер в ``modules.bulk.actions``.
    """

    SET_PERSONA = "set_persona"
    LOGOUT_OTHER_SESSIONS = "logout_other_sessions"
    SET_PRIVACY = "set_privacy"
    APPLY_PROFILE = "apply_profile"
    GENERATE_AND_APPLY_PROFILE = "generate_and_apply_profile"
    SET_2FA = "set_2fa"
    JOIN_CHANNELS = "join_channels"
    LEAVE_CHANNELS = "leave_channels"
    VIEW_CHANNEL_POSTS = "view_channel_posts"
    PUBLISH_STORY = "publish_story"
    VIEW_STORIES = "view_stories"
    ASSIGN_PROXY = "assign_proxy"
    APPLY_PROFILE_POOL = "apply_profile_pool"
    SEND_REACTIONS = "send_reactions"
