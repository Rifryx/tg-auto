"""Сервисный слой источника чатов масс-реакций (spec §2).

Координирует разбор списка, добавление чатов и применение результата резолва/
подписки через репозитории. Telethon-резолв и постановка join-задач — на
финальном интеграционном шаге; эти функции вызываются и из API, и из воркера.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from modules.mass_reactions.chats import (
    normalize_chat_ref,
    parse_chat_list,
    resolve_chat_state,
)
from modules.mass_reactions.models import MassReactionCampaignChat
from modules.mass_reactions.repositories import CampaignChatRepository
from modules.mass_reactions.schemas.enums import ChatNotifyMode, ChatState


def add_chats_from_list(
    session: Session,
    campaign_id: int,
    raw_text: str,
    *,
    notify_mode: str = ChatNotifyMode.NOTIFY_ONLY.value,
) -> list[MassReactionCampaignChat]:
    """Добавляет чаты из вставленного списка. Дубли (по chat_ref) — молча."""
    repo = CampaignChatRepository(session)
    existing = {c.chat_ref for c in repo.list_by_campaign(campaign_id)}
    created: list[MassReactionCampaignChat] = []
    for ref in parse_chat_list(raw_text):
        if ref in existing:
            continue
        existing.add(ref)
        created.append(
            repo.create(
                {
                    "campaign_id": campaign_id,
                    "chat_ref": ref,
                    "notify_mode": notify_mode,
                    "state": ChatState.PENDING.value,
                }
            )
        )
    return created


def add_single_chat(
    session: Session,
    campaign_id: int,
    raw_ref: str,
    *,
    notify_mode: str = ChatNotifyMode.NOTIFY_ONLY.value,
) -> Optional[MassReactionCampaignChat]:
    """Добавляет один чат; ``None`` если ref пустой/мусор или уже есть."""
    ref = normalize_chat_ref(raw_ref)
    if not ref:
        return None
    repo = CampaignChatRepository(session)
    if any(c.chat_ref == ref for c in repo.list_by_campaign(campaign_id)):
        return None
    return repo.create(
        {
            "campaign_id": campaign_id,
            "chat_ref": ref,
            "notify_mode": notify_mode,
            "state": ChatState.PENDING.value,
        }
    )


def apply_resolution(
    session: Session,
    chat_id: int,
    *,
    chat_tg_id: int,
    title: Optional[str],
    subscribed: bool,
) -> Optional[MassReactionCampaignChat]:
    """Фиксирует результат резолва и проверки подписки.

    Состояние считается из факта подписки и ``notify_mode`` чата:
    подписан → active, иначе notify_only → not_subscribed / notify_and_join →
    joining (воркер поставит задачу вступления).
    """
    repo = CampaignChatRepository(session)
    chat = repo.get(chat_id)
    if chat is None:
        return None
    state = resolve_chat_state(subscribed=subscribed, notify_mode=chat.notify_mode)
    return repo.update(
        chat_id, {"chat_tg_id": chat_tg_id, "title": title, "state": state}
    )


def mark_joined(session: Session, chat_id: int) -> Optional[MassReactionCampaignChat]:
    """После успешного вступления чат уходит в работу."""
    return CampaignChatRepository(session).update(
        chat_id, {"state": ChatState.ACTIVE.value}
    )


def mark_failed(session: Session, chat_id: int) -> Optional[MassReactionCampaignChat]:
    """Не удалось зарезолвить/вступить."""
    return CampaignChatRepository(session).update(
        chat_id, {"state": ChatState.FAILED.value}
    )
