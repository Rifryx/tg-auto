"""Постановка одной реакции с записью в лог (spec §1, §5).

``place_reaction`` вызывается задачей ``mass_reactions.place_reaction`` для пары
(чат × аккаунт × сообщение). Реальная отправка инжектируется колбэком ``send``
(в задаче — Telethon через governor), поэтому исход и логирование тестируемы без
Telethon. FloodWait/карантин/failover (управление состоянием аккаунта) —
отдельный шаг; здесь фиксируем исход и счётчики успешной реакции.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from modules.mass_reactions.repositories import (
    CampaignAccountRepository,
    CampaignChatRepository,
    LogRepository,
)
from modules.mass_reactions.schemas.enums import ReactionOutcome
from modules.mass_reactions.worker.errors import classify_reaction_error


async def place_reaction(
    *,
    session_factory: Callable[[], object],
    send: Callable[[int, int, str], Awaitable[None]],
    campaign_id: int,
    chat_id: int,
    account_id: int,
    chat_tg_id: int,
    msg_id: int,
    emoji: str,
    dry_run: bool = False,
    now_fn: Optional[Callable[[], datetime]] = None,
) -> ReactionOutcome:
    """Ставит реакцию и пишет строку в ``execution_log``. Возвращает исход."""
    now = now_fn or (lambda: datetime.now(timezone.utc))
    started = now()

    outcome = ReactionOutcome.REACTED
    error_code: Optional[str] = None
    flood_wait_sec: Optional[int] = None
    if dry_run:
        pass  # симуляция — реального вызова нет, исход REACTED
    else:
        try:
            await send(chat_tg_id, msg_id, emoji)
        except Exception as exc:  # noqa: BLE001 — любой сбой классифицируем
            err = classify_reaction_error(exc)
            outcome = err.outcome
            error_code = err.error_code
            flood_wait_sec = err.flood_wait_sec

    finished = now()
    latency_ms = max(0, int((finished - started).total_seconds() * 1000))

    with session_factory() as session:  # type: ignore[operator]
        LogRepository(session).append(
            campaign_id=campaign_id,
            account_id=account_id,
            chat_id=chat_id,
            outcome=outcome.value,
            started_at=started,
            finished_at=finished,
            message_tg_id=msg_id,
            emoji=emoji if outcome == ReactionOutcome.REACTED else None,
            error_code=error_code,
            flood_wait_sec=flood_wait_sec,
            latency_ms=latency_ms,
            dry_run=dry_run,
        )
        if outcome == ReactionOutcome.REACTED and not dry_run:
            CampaignChatRepository(session).mark_reacted(chat_id, when=finished)
            CampaignAccountRepository(session).register_reaction(
                account_id, when=finished
            )
        session.commit()

    return outcome
