"""Enum'ы модуля прайминга (промпт 1.2).

Единый источник значений для ORM (CheckConstraint), сервисного слоя и API.
Собран здесь, а не в ``core/enums/``, потому что enum'ы модуля-специфичные
и не переиспользуются другими модулями (кросс-модульные общие типы, если
понадобятся, всё ещё живут в ``core/enums/``).

Значения — snake_case строки; ORM и Alembic-миграции сравнивают именно
`enum.value`, не имя.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Iterable


class PrimingCampaignStatus(StrEnum):
    """Жизненный цикл кампании прайминга (spec §4.1)."""

    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FINISHED = "finished"
    FAILED = "failed"


class PrimingMode(StrEnum):
    """Режим модуля. Пока один — задел под возможные варианты."""

    PRIMING = "priming"


class TriggerAction(StrEnum):
    """MTProto-действия, инициирующие push у цели (spec §5).

    Реестр пополняется по результатам R&D (``docs/priming-triggers.md``).
    """

    SET_TTL_1D = "set_ttl_1d"
    SET_TTL_OFF = "set_ttl_off"
    SET_CONTENT_PROTECTION = "set_content_protection"
    SECRET_CHAT_REQUEST = "secret_chat_request"
    CONTACT_ADDED = "contact_added"
    CONTACT_REMOVED = "contact_removed"
    PINNED_MESSAGE_PING = "pinned_message_ping"


class HumanizerMode(StrEnum):
    """Интенсивность фоновой имитации (spec §10)."""

    OFF = "off"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class WarmupProfile(StrEnum):
    """Пресеты стартовых лимитов (spec §11.1)."""

    COLD = "cold"
    WARM = "warm"
    HOT = "hot"


class PrimingAccountState(StrEnum):
    """Состояние аккаунта-инициатора внутри кампании (spec §4.2)."""

    IDLE = "idle"
    WORKING = "working"
    COOLDOWN = "cooldown"
    QUARANTINED = "quarantined"
    DISABLED = "disabled"


class TargetStatus(StrEnum):
    """Жизненный цикл цели (spec §4.3).

    Терминальные состояния: PRIMED, BLACKLISTED. FAILED/SKIPPED — не
    терминальные: цель может быть повторно поставлена в очередь при
    следующем прогоне.
    """

    PENDING = "pending"
    ASSIGNED = "assigned"
    PRIMED = "primed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLACKLISTED = "blacklisted"


# Разрешённые переходы TargetStatus. Ключ — текущее состояние; значение —
# набор допустимых следующих. Всё, чего тут нет, — запрещено.
_TARGET_STATUS_TRANSITIONS: dict[TargetStatus, frozenset[TargetStatus]] = {
    TargetStatus.PENDING: frozenset(
        {TargetStatus.ASSIGNED, TargetStatus.SKIPPED, TargetStatus.BLACKLISTED}
    ),
    TargetStatus.ASSIGNED: frozenset(
        {
            TargetStatus.PRIMED,
            TargetStatus.FAILED,
            TargetStatus.SKIPPED,
            TargetStatus.BLACKLISTED,
            # Ре-освобождение при рестарте worker'а (advisory-lock отпущен,
            # цель вернулась в очередь).
            TargetStatus.PENDING,
        }
    ),
    TargetStatus.FAILED: frozenset(
        {TargetStatus.PENDING, TargetStatus.BLACKLISTED}
    ),
    TargetStatus.SKIPPED: frozenset(
        {TargetStatus.PENDING, TargetStatus.BLACKLISTED}
    ),
    # Терминальные.
    TargetStatus.PRIMED: frozenset(),
    TargetStatus.BLACKLISTED: frozenset(),
}


def target_status_allowed_transitions(
    current: TargetStatus,
) -> frozenset[TargetStatus]:
    return _TARGET_STATUS_TRANSITIONS.get(current, frozenset())


def can_target_status_transition(
    current: TargetStatus, next_status: TargetStatus
) -> bool:
    return next_status in target_status_allowed_transitions(current)


class TargetLastSeen(StrEnum):
    """Бакет активности цели по ``user.status`` (spec §4.3)."""

    RECENTLY = "recently"
    WITHIN_WEEK = "within_week"
    WITHIN_MONTH = "within_month"
    LONG_AGO = "long_ago"
    UNKNOWN = "unknown"


class ExecutionOutcome(StrEnum):
    """Исход одной попытки прайминга (spec §4.7).

    Кроме списка из спеки добавлены две новых причины:
    - ``ALREADY_APPLIED`` — состояние цели уже совпадает с action'ом (см.
      TriggerRunner в промпте 2.1), поэтому ничего не отправляем;
    - ``SKIPPED_QUIET`` — цель попала в «тихие часы» (промпт 7.2).
    """

    PRIMED = "primed"
    ALREADY_APPLIED = "already_applied"
    FLOOD_WAIT = "flood_wait"
    PRIVACY_RESTRICTED = "privacy_restricted"
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    CHANNEL_PINNED_ERROR = "channel_pinned_error"
    SKIPPED_QUIET = "skipped_quiet"
    INTERNAL_ERROR = "internal_error"


class ParserSourceKind(StrEnum):
    """Источник, из которого собран пул целей (spec §4.4)."""

    CHAT_MESSAGES = "chat_messages"
    CHAT_MEMBERS = "chat_members"
    MANUAL_LIST = "manual_list"
    UPLOAD_CSV = "upload_csv"
    # Extraction+ (этап 1 расширения парсера):
    CHANNEL_COMMENTERS = "channel_commenters"  # комментаторы из linked-чата канала
    POST_REACTORS = "post_reactors"            # кто ставил реакции на посты
    LIST_OP = "list_op"                        # производный список (операции над списками)


class BlacklistReason(StrEnum):
    """Причина попадания цели в blacklist (spec §4.9)."""

    MANUAL = "manual"
    PRIVACY_RESTRICTED = "privacy_restricted"
    ALREADY_PRIMED_RECENTLY = "already_primed_recently"
    BOT = "bot"
    DELETED = "deleted"
    COMPLAINT = "complaint"


class TriggerRotationStrategy(StrEnum):
    """Как выбирать очередной ``TriggerAction`` из списка (spec §5, 5.2).

    ``random`` — независимая случайная выборка каждый прайм.
    ``round_robin`` — циклический перебор по индексу.
    ``weighted`` — random с весами (задел; веса появятся с UI, MVP =
    равномерный, т.е. вырождается в random).
    """

    RANDOM = "random"
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"


class AnchorChannelState(StrEnum):
    """Состояние закреплённого канала-переходника (spec §4.6)."""

    OK = "ok"
    BROKEN = "broken"
    RESET_REQUIRED = "reset_required"


def all_enums() -> Iterable[type[StrEnum]]:
    """Реестр enum'ов модуля — для миграций/интроспекции."""
    return (
        PrimingCampaignStatus,
        PrimingMode,
        TriggerAction,
        HumanizerMode,
        WarmupProfile,
        PrimingAccountState,
        TargetStatus,
        TargetLastSeen,
        ExecutionOutcome,
        ParserSourceKind,
        BlacklistReason,
        AnchorChannelState,
        TriggerRotationStrategy,
    )


__all__ = [
    "PrimingCampaignStatus",
    "PrimingMode",
    "TriggerAction",
    "HumanizerMode",
    "WarmupProfile",
    "PrimingAccountState",
    "TargetStatus",
    "TargetLastSeen",
    "ExecutionOutcome",
    "ParserSourceKind",
    "BlacklistReason",
    "AnchorChannelState",
    "TriggerRotationStrategy",
    "target_status_allowed_transitions",
    "can_target_status_transition",
    "all_enums",
]
