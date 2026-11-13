"""Enum'ы модуля масс-реакций.

Единый источник значений для ORM (CheckConstraint), сервисного слоя и API.
Модуль-специфичные (как в priming): значения — snake_case строки, ORM и
Alembic сравнивают именно ``enum.value``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Iterable


class MassReactionCampaignStatus(StrEnum):
    """Жизненный цикл кампании масс-реакций."""

    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FINISHED = "finished"
    FAILED = "failed"


class ChatSourceMode(StrEnum):
    """Откуда берём чаты (близнец ``channel_source_mode`` нейрокомментинга)."""

    BY_SUBSCRIPTIONS = "by_subscriptions"  # группы, где аккаунт уже состоит
    EXPLICIT_LIST = "explicit_list"        # пользователь ввёл @username / ссылки


class ChatNotifyMode(StrEnum):
    """Что делать с чатом из списка, которого нет в подписках аккаунта."""

    NOTIFY_ONLY = "notify_only"        # только пометить, реакции не ставим
    NOTIFY_AND_JOIN = "notify_and_join"  # поставить задачу вступления, затем в работу


class ChatState(StrEnum):
    """Состояние закреплённого чата внутри кампании."""

    PENDING = "pending"              # ждёт резолва/проверки подписки
    ACTIVE = "active"                # слушается, реакции идут
    NOT_SUBSCRIBED = "not_subscribed"  # нет в подписках, notify_only
    JOINING = "joining"              # идёт вступление (notify_and_join)
    FAILED = "failed"                # не удалось зарезолвить/вступить
    DISABLED = "disabled"            # выключен вручную


class MassReactionAccountState(StrEnum):
    """Состояние аккаунта-инициатора внутри кампании (как в priming)."""

    IDLE = "idle"
    WORKING = "working"
    COOLDOWN = "cooldown"
    QUARANTINED = "quarantined"
    DISABLED = "disabled"


class ReactionStrategy(StrEnum):
    """Как выбирать эмодзи из набора на каждую реакцию."""

    RANDOM = "random"            # случайный из выбранных
    ROUND_ROBIN = "round_robin"  # по кругу


class WarmupProfile(StrEnum):
    """Пресеты стартовых лимитов (cold / warm / hot), как в priming."""

    COLD = "cold"
    WARM = "warm"
    HOT = "hot"


class HumanizerMode(StrEnum):
    """Интенсивность фоновой имитации между реакциями."""

    OFF = "off"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class ReactionOutcome(StrEnum):
    """Исход одной попытки поставить реакцию (append-only лог)."""

    REACTED = "reacted"
    SKIPPED_NOT_HUMAN = "skipped_not_human"  # бот/служебное/свой аккаунт
    SKIPPED_FILTER = "skipped_filter"        # не прошёл N-охват / вероятность / «старше N дней»
    SKIPPED_QUIET = "skipped_quiet"          # тихие часы
    FLOOD_WAIT = "flood_wait"
    PEER_FLOOD = "peer_flood"
    FORBIDDEN = "forbidden"                  # нет прав / реакции запрещены в чате
    NOT_FOUND = "not_found"                  # сообщение удалено/недоступно
    INTERNAL_ERROR = "internal_error"


def all_enums() -> Iterable[type[StrEnum]]:
    """Реестр enum'ов модуля — для миграций/интроспекции."""
    return (
        MassReactionCampaignStatus,
        ChatSourceMode,
        ChatNotifyMode,
        ChatState,
        MassReactionAccountState,
        ReactionStrategy,
        WarmupProfile,
        HumanizerMode,
        ReactionOutcome,
    )


__all__ = [
    "MassReactionCampaignStatus",
    "ChatSourceMode",
    "ChatNotifyMode",
    "ChatState",
    "MassReactionAccountState",
    "ReactionStrategy",
    "WarmupProfile",
    "HumanizerMode",
    "ReactionOutcome",
    "all_enums",
]
