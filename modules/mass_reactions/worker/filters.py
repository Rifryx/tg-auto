"""Чистая логика отбора сообщений и реакций (spec §1, §3).

Ничего не знает о Telethon/БД — только значения. Благодаря этому вся
«решающая» механика покрыта быстрыми юнит-тестами.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from modules.mass_reactions.schemas.enums import ReactionStrategy


def is_live_human(
    *,
    sender_id: Optional[int],
    is_user: bool,
    is_bot: bool,
    is_service: bool,
    is_outgoing: bool,
    own_account_ids: Iterable[int] = (),
) -> bool:
    """True — сообщение отправлено живым человеком-целью воронки (spec §1).

    Мимо идут: анонимные/канальные отправители (``sender_id is None`` или не
    user), служебные сообщения, боты, наши собственные сообщения и аккаунты
    пула — реакция должна уходить реальной цели, а не себе/боту.
    """
    if sender_id is None:
        return False
    if is_service or is_outgoing:
        return False
    if not is_user:
        return False
    if is_bot:
        return False
    if sender_id in set(own_account_ids):
        return False
    return True


def is_message_too_old(
    message_date: Optional[datetime],
    *,
    now: Optional[datetime] = None,
    skip_older_than_days: int,
) -> bool:
    """True — сообщение старше порога и его надо пропустить (spec §3).

    ``skip_older_than_days == 0`` → реагируем только на свежий поток (любой
    возраст > 0 считается старым). Без даты сообщения считаем не старым.
    """
    if message_date is None:
        return False
    now = now or datetime.now(timezone.utc)
    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)
    return (now - message_date) > timedelta(days=skip_older_than_days)


def should_react(
    *,
    counter: int,
    every_n_message: int,
    probability_percent: int,
    rng: Optional[random.Random] = None,
) -> bool:
    """Решение «ставить ли реакцию» на текущее (counter-е) сообщение чата.

    - ``every_n_message`` — считаем по чату: реагируем, когда ``counter`` кратен
      N (при N<=1 — каждое сообщение проходит счётчик);
    - затем ``probability_percent`` — коин-флип 0..99 < p.
    ``counter`` — это номер входящего человеческого сообщения в чате (1-based),
    уже увеличенный на текущее сообщение.
    """
    rng = rng or random.Random()
    n = max(1, every_n_message)
    if counter % n != 0:
        return False
    p = max(0, min(100, probability_percent))
    return rng.randrange(100) < p


def pick_emoji(
    emojis: Sequence[str],
    *,
    strategy: str = ReactionStrategy.RANDOM.value,
    counter: int = 1,
    rng: Optional[random.Random] = None,
) -> Optional[str]:
    """Выбирает эмодзи из набора по стратегии. Пустой набор → None."""
    items = [e for e in emojis if e]
    if not items:
        return None
    if strategy == ReactionStrategy.ROUND_ROBIN.value:
        return items[(max(1, counter) - 1) % len(items)]
    rng = rng or random.Random()
    return rng.choice(items)
