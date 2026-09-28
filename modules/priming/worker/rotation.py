"""Выбор конкретного ``TriggerAction`` из списка кампании (промпт 5.2).

Executor вызывает :func:`pick_trigger_action` в момент старта прайминга.
Стратегия — на уровне кампании (``TriggerRotationStrategy``). Round-robin
использует ``primes_total`` аккаунта как счётчик, чтобы не хранить
отдельный курсор.
"""

from __future__ import annotations

import random
from typing import Sequence

from modules.priming.schemas.enums import (
    TriggerAction,
    TriggerRotationStrategy,
)


def pick_trigger_action(
    actions: Sequence[str],
    strategy: TriggerRotationStrategy,
    *,
    counter: int = 0,
    rng: random.Random | None = None,
) -> TriggerAction:
    """Возвращает ``TriggerAction`` из ``actions`` по указанной стратегии.

    * ``actions`` — не должен быть пустым (Alembic CHECK гарантирует это
      на уровне БД, но здесь тоже страхуемся).
    * ``counter`` — для round_robin (обычно ``campaign_account.primes_total``).
    * ``rng`` — детерминизируется в тестах.
    """
    if not actions:
        raise ValueError("trigger_actions is empty")
    values = [TriggerAction(a) for a in actions]

    if strategy is TriggerRotationStrategy.ROUND_ROBIN:
        return values[counter % len(values)]

    # random и weighted: MVP-weighted = uniform (веса подъедут позже).
    return (rng or random.Random()).choice(values)
