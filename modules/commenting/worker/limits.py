"""Лимиты работы кампании (E2.2): макс. комментариев, мин. слов, окно после
поста, пауза между комментами аккаунта.

Общие для обеих веток раннера (кампания-центричной и аккаунт-центричной).
Режим (``campaigns.work_mode``):
* ``by_count``        — действует ``max_comments``;
* ``by_time_window``  — плюс окно ``window_after_post_sec`` и пауза
  ``pause_between_sec``.
``max_comments`` и ``min_words`` действуют в обоих режимах.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select

from core.enums import CommentStatus
# Через core.models: прямой импорт modules.commenting.models первым ловит
# старый цикл core.models <-> modules.commenting.models.
from core.models import CampaignAccount, CommentLog

TIME_WINDOW = "by_time_window"
# Сколько раз всего просим LLM, если текст короче min_words.
MIN_WORDS_ATTEMPTS = 3

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def word_count(text: str) -> int:
    """Слова = последовательности букв/цифр (эмодзи и пунктуация не считаются)."""
    return len(_WORD.findall(text or ""))


def posted_count(session, campaign_id: int) -> int:
    return session.execute(
        select(func.count())
        .select_from(CommentLog)
        .where(
            CommentLog.campaign_id == campaign_id,
            CommentLog.status == CommentStatus.POSTED.value,
        )
    ).scalar_one()


def max_comments_reached(session, campaign) -> bool:
    """Лимит считается по ОПУБЛИКОВАННЫМ: неудачные попытки его не съедают.

    Параллельные отправки могут превысить лимит на число одновременно
    работающих задач воркера — точнее без резервирования слотов не сделать.
    """
    limit = campaign.max_comments
    return limit is not None and posted_count(session, campaign.id) >= limit


def post_date_from_ts(post_date_ts: Optional[float]) -> Optional[datetime]:
    if post_date_ts is None:
        return None
    return datetime.fromtimestamp(post_date_ts, tz=timezone.utc)


def window_closed(campaign, post_date: Optional[datetime], now: datetime) -> bool:
    """Окно «после публикации поста» истекло.

    Нет даты поста (старые задачи, тред без даты) — не блокируем: лучше
    лишний коммент, чем молча выключить кампанию.
    """
    if campaign.work_mode != TIME_WINDOW or not campaign.window_after_post_sec:
        return False
    if post_date is None:
        return False
    return now - post_date > timedelta(seconds=campaign.window_after_post_sec)


def _pause(campaign) -> Optional[timedelta]:
    if campaign.work_mode != TIME_WINDOW or not campaign.pause_between_sec:
        return None
    return timedelta(seconds=campaign.pause_between_sec)


def pause_wait_until(link: Optional[CampaignAccount], campaign, now: datetime) -> Optional[datetime]:
    """Когда аккаунту снова можно комментировать (None — можно сейчас).

    Проверка без блокировки — чтобы не тратить слот governor'а зря.
    """
    pause = _pause(campaign)
    if pause is None or link is None or link.last_posted_at is None:
        return None
    ready_at = link.last_posted_at + pause
    return ready_at if now < ready_at else None


def claim_post_slot(session, campaign, account_id: int, now: datetime) -> Optional[datetime]:
    """Атомарно занять «слот» аккаунта: SELECT … FOR UPDATE + отметка времени.

    Возвращает None, если слот занят успешно (last_posted_at = now), иначе —
    момент, когда пауза закончится. Коммитит транзакцию сам.
    Отметка ставится ДО отправки: две задачи одного аккаунта не проскочат
    паузу одновременно.
    """
    link = session.execute(
        select(CampaignAccount)
        .where(
            CampaignAccount.campaign_id == campaign.id,
            CampaignAccount.account_id == account_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if link is None:
        session.rollback()
        return None
    wait = pause_wait_until(link, campaign, now)
    if wait is not None:
        session.rollback()
        return wait
    link.last_posted_at = now
    session.commit()
    return None


async def generate_with_min_words(generate_once, min_words: int) -> tuple[str, bool]:
    """Генерирует текст, пока в нём не наберётся ``min_words`` слов.

    ``generate_once`` — async-функция без аргументов, возвращает готовый
    (уже стилизованный) текст. Возвращает (текст, ok); при ok=False в тексте —
    последняя попытка (для лога).
    """
    text = await generate_once()
    if min_words <= 0:
        return text, True
    for _ in range(MIN_WORDS_ATTEMPTS - 1):
        if word_count(text) >= min_words:
            return text, True
        text = await generate_once()
    return text, word_count(text) >= min_words
