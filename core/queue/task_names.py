"""Константные имена задач и очередей arq (PROJECT-STAGES §2, §4).

Единственный источник допустимых имён задач: enqueue разрешает только значения
из :class:`TaskName`. Бизнес-логика задач здесь не живёт — только идентификаторы.
"""

from enum import Enum


class TaskName(str, Enum):
    """Полный список задач (PROJECT-STAGES §2)."""

    # --- Shared ---
    ACCOUNT_LOGIN_START = "account.login_start"
    ACCOUNT_LOGIN_CONFIRM = "account.login_confirm"
    ACCOUNT_LOGIN_PASSWORD = "account.login_password"
    WARMING_INITIAL_START = "warming.initial_start"
    WARMING_TICK = "warming.tick"
    WARMING_MAINTENANCE_SCHEDULER = "warming.maintenance_scheduler"
    HEALTH_CHECK_PROXIES = "health.check_proxies"
    HEALTH_COOLDOWN_RETURN = "health.cooldown_return"
    HEALTH_CHECK_ACCOUNT = "health.check_account"
    HEALTH_CHECK_ACCOUNTS_PERIODIC = "health.check_accounts_periodic"
    HEALTH_RECOMPUTE_SCORE = "health.recompute_score"
    BULK_DISPATCH = "bulk.dispatch"
    BULK_ITEM = "bulk.item"
    ACCOUNT_RETIRE = "account.retire"
    ACCOUNT_ACKNOWLEDGE_BAN = "account.acknowledge_ban"

    # --- Модуль commenting ---
    COMMENTING_ON_NEW_POST = "commenting.on_new_post"
    COMMENTING_POST_COMMENT = "commenting.post_comment"
    # Аккаунт-центричный мониторинг каналов (у каждого аккаунта свои каналы):
    COMMENTING_RESOLVE_CHANNEL = "commenting.resolve_channel"
    COMMENTING_LEAVE_CHANNEL = "commenting.leave_channel"
    COMMENTING_ON_CHANNEL_POST = "commenting.on_channel_post"
    COMMENTING_POST_CHANNEL_COMMENT = "commenting.post_channel_comment"


class QueueName(str, Enum):
    """Логические очереди arq.

    ``default`` — единственная активная очередь на текущем этапе. ``high``
    заведена под будущий high-приоритет, но пока в неё ничего не маршрутизируется.
    """

    DEFAULT = "default"
    HIGH = "high"
