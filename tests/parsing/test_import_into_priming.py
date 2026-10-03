"""Промпт 3.2b: import_from_parsed_list копирует parsing.list_targets
в priming.campaign_targets."""

from __future__ import annotations

import itertools

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.parsing.repositories import (
    ParsedListRepository,
    ParsedListTargetRepository,
)
from modules.priming.api.service import import_from_parsed_list
from modules.priming.repositories import (
    BlacklistRepository,
    CampaignRepository,
    CampaignTargetRepository,
)
from modules.priming.schemas.enums import BlacklistReason, TriggerAction


_PHONE = itertools.count(90_300_000_000)


def _campaign(session) -> int:
    c = CampaignRepository(session).create({
        "name": "c",
        "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
        "created_by": 7,
    })
    session.commit()
    return c.id


def _parsed_list(session, targets: list[dict]) -> int:
    plist = ParsedListRepository(session).create({
        "owner_user_id": 7, "name": "l", "source_kind": "chat_messages",
    })
    ParsedListTargetRepository(session).bulk_create(plist.id, targets)
    session.commit()
    return plist.id


def test_import_from_parsed_list_dedupes_and_blacklists(session) -> None:
    campaign_id = _campaign(session)
    # Наливаем 3 таргета, один blacklist-ится глобально.
    BlacklistRepository(session).create({
        "owner_user_id": None, "tg_user_id": 999,
        "reason": BlacklistReason.MANUAL.value,
    })
    session.commit()

    list_id = _parsed_list(session, [
        {"tg_user_id": 111, "username": "alice"},
        {"tg_user_id": 222, "username": "bob"},
        {"tg_user_id": 999, "username": "shady"},
    ])

    result = import_from_parsed_list(
        session, campaign_id, list_id, owner_user_id=7,
    )
    session.commit()
    assert result.inserted == 2
    assert result.skipped_blacklisted == 1

    ids = {
        t.tg_user_id
        for t in CampaignTargetRepository(session).list_by_campaign(campaign_id)
    }
    assert ids == {111, 222}


def test_import_missing_parsed_list_404(session) -> None:
    campaign_id = _campaign(session)
    from modules.priming.api.service import NotFoundError

    with pytest.raises(NotFoundError):
        import_from_parsed_list(session, campaign_id, 99999)
