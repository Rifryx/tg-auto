"""Слушатель сообщений чата для масс-реакций (spec §1–§3).

На каждое новое сообщение в закреплённом чате:
  1. отсеиваем не-людей (боты, служебные, свои, анонимы) и старые сообщения;
  2. дедуп по сообщению (повтор события не считаем дважды);
  3. увеличиваем счётчик чата «каждое N-е» и решаем, реагировать ли;
  4. при «да» — ставим задачу на реакцию через очередь.

Счётчик и очередь переданы колбэками (``increment_counter`` / ``enqueue_reaction``),
поэтому хендлер не зависит от конкретной БД/очереди и полностью тестируем.
Привязка к реальному session/governor живёт в реестре слушателей и tick
(подключается следующим шагом).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable, Optional

from modules.mass_reactions.schemas.enums import ReactionStrategy
from modules.mass_reactions.worker.filters import (
    is_live_human,
    is_message_too_old,
    pick_emoji,
    should_react,
)


@dataclass(frozen=True)
class MessageFacts:
    sender_id: Optional[int]
    is_user: bool
    is_bot: bool
    is_service: bool
    is_outgoing: bool
    message_id: Optional[int]
    date: Optional[datetime]


def extract_message_facts(message: Any) -> MessageFacts:
    """Достаёт из Telethon-сообщения признаки для фильтра (с безопасными
    дефолтами; для тестов достаточно обычного объекта с теми же атрибутами)."""
    cls = type(message).__name__
    is_service = cls == "MessageService" or getattr(message, "action", None) is not None
    sender = getattr(message, "sender", None)
    is_bot = bool(getattr(sender, "bot", False))
    # Пост канала / анонимный админ → не человек (есть post=True или sender не User).
    is_post = bool(getattr(message, "post", False))
    sender_cls = type(sender).__name__ if sender is not None else None
    is_user = (not is_post) and (sender is None or sender_cls == "User")
    return MessageFacts(
        sender_id=getattr(message, "sender_id", None),
        is_user=is_user,
        is_bot=is_bot,
        is_service=is_service,
        is_outgoing=bool(getattr(message, "out", False)),
        message_id=getattr(message, "id", None),
        date=getattr(message, "date", None),
    )


def _claim_once(redis: Any, key: str, ttl: int = 900) -> bool:
    """SETNX: True — первый раз, False — повтор. Без redis (тесты) всегда True."""
    if redis is None:
        return True
    try:
        return bool(redis.set(key, "1", nx=True, ex=ttl))
    except Exception:  # noqa: BLE001 — fail-open: лучше обработать, чем молчать
        return True


def make_chat_message_handler(
    *,
    campaign_id: int,
    chat_id: int,
    account_id: int,
    every_n_message: int,
    probability_percent: int,
    skip_older_than_days: int,
    emojis: list[str],
    reaction_strategy: str = ReactionStrategy.RANDOM.value,
    increment_counter: Callable[[], int],
    enqueue_reaction: Callable[[int, str], Awaitable[None]],
    own_account_ids: Iterable[int] = (),
    rng: Optional[random.Random] = None,
    redis: Any = None,
    now_fn: Optional[Callable[[], datetime]] = None,
) -> Callable[[Any], Awaitable[None]]:
    """Возвращает async-хендлер события нового сообщения в чате.

    ``increment_counter`` вызывается РОВНО для сообщений, прошедших фильтр
    «живой человек + не старое + не дубль», и должен атомарно увеличить
    счётчик чата и вернуть новое значение (на нём считается «каждое N-е»).
    """
    _rng = rng or random.Random()
    _own = set(own_account_ids)

    async def handler(event: Any) -> None:
        message = getattr(event, "message", event)
        facts = extract_message_facts(message)

        if not is_live_human(
            sender_id=facts.sender_id,
            is_user=facts.is_user,
            is_bot=facts.is_bot,
            is_service=facts.is_service,
            is_outgoing=facts.is_outgoing,
            own_account_ids=_own,
        ):
            return
        if facts.message_id is None:
            return
        if is_message_too_old(
            facts.date,
            now=now_fn() if now_fn else None,
            skip_older_than_days=skip_older_than_days,
        ):
            return
        if not _claim_once(redis, f"mr:listen:{campaign_id}:{chat_id}:{facts.message_id}"):
            return

        # Считаем ТОЛЬКО сообщения, прошедшие фильтр (счётчик «каждое N-е» по чату).
        counter = increment_counter()
        if not should_react(
            counter=counter,
            every_n_message=every_n_message,
            probability_percent=probability_percent,
            rng=_rng,
        ):
            return
        emoji = pick_emoji(
            emojis, strategy=reaction_strategy, counter=counter, rng=_rng
        )
        if not emoji:
            return
        await enqueue_reaction(facts.message_id, emoji)

    return handler
