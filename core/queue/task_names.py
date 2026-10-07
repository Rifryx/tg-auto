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
    HEALTH_PREDICT_BAN_RISK = "health.predict_ban_risk"
    HEALTH_PREDICT_BAN_RISK_BATCH = "health.predict_ban_risk_batch"
    AUTOPILOT_TICK = "autopilot.tick"
    # Security: recovery-email flow для 2FA (этап 7, backlog #1).
    SECURITY_REQUEST_RECOVERY_EMAIL = "security.request_recovery_email"
    SECURITY_CONFIRM_RECOVERY_EMAIL = "security.confirm_recovery_email"
    BULK_DISPATCH = "bulk.dispatch"
    BULK_ITEM = "bulk.item"
    # Биллинг: периодическая сверка pending крипто-платежей с Crypto Pay API.
    BILLING_RECONCILE_PAYMENTS = "billing.reconcile_payments"
    ACCOUNT_RETIRE = "account.retire"
    ACCOUNT_ACKNOWLEDGE_BAN = "account.acknowledge_ban"

    # --- Модуль commenting ---
    COMMENTING_ON_NEW_POST = "commenting.on_new_post"
    COMMENTING_POST_COMMENT = "commenting.post_comment"
    # Аккаунт-центричный мониторинг каналов (у каждого аккаунта свои каналы):
    COMMENTING_RESOLVE_CHANNEL = "commenting.resolve_channel"
    COMMENTING_LEAVE_CHANNEL = "commenting.leave_channel"
    COMMENTING_SYNC_CAMPAIGN_CHANNELS = "commenting.sync_campaign_channels"
    COMMENTING_SYNC_ACCOUNT_SUBSCRIPTIONS = "commenting.sync_account_subscriptions"
    COMMENTING_BACKFILL_CHANNEL = "commenting.backfill_channel"
    COMMENTING_VERIFY_COMMENT = "commenting.verify_comment"
    COMMENTING_ON_CHANNEL_POST = "commenting.on_channel_post"
    COMMENTING_POST_CHANNEL_COMMENT = "commenting.post_channel_comment"

    # --- Модуль shilling ---
    # Идентификаторы задач объявлены здесь (нужны API-роутам start/stop/dry-run,
    # промпт 2.4); регистрация обработчиков и бизнес-логика — промпты 4.1–4.5.
    SHILLING_START_CAMPAIGN = "shilling.start_campaign"
    SHILLING_PROCESS_TARGET = "shilling.process_target"
    SHILLING_EXECUTE_STEP = "shilling.execute_step"
    SHILLING_FAILOVER = "shilling.failover"
    SHILLING_DRY_RUN = "shilling.dry_run"

    # --- Модуль priming ---
    # execute_prime — один прайм (target × campaign_account, промпт 2.2).
    # orchestrator_tick — раскладывает пары и планирует execute_prime
    # (промпт 2.3). humanizer_beat — фоновая имитация (промпт 5.1).
    PRIMING_EXECUTE_PRIME = "priming.execute_prime"
    PRIMING_ORCHESTRATOR_TICK = "priming.orchestrator_tick"
    PRIMING_HUMANIZER_BEAT = "priming.humanizer_beat"
    # PRIMING_PARSER_RUN оставлен под уже настроенный enqueue из
    # /modules/parsing/lists/run/*; сам хендлер живёт в modules/parsing.
    PRIMING_PARSER_RUN = "priming.parser_run"
    # PRIMING_PROFILE_APPLY удалён: оформление профилей — не задача
    # priming. Работает через bulk-действия из modules/bulk/actions/
    # (apply_profile, apply_profile_pool, generate_and_apply_profile).


class QueueName(str, Enum):
    """Логические очереди arq.

    ``default`` — единственная активная очередь на текущем этапе. ``high``
    заведена под будущий high-приоритет, но пока в неё ничего не маршрутизируется.
    """

    DEFAULT = "default"
    HIGH = "high"
