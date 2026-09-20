"""Юнит-тесты send_reactions payload и парсера URL (этап 8, backlog #3).

Без БД и без Telethon — только парсеры и валидация.
"""

from __future__ import annotations

import pytest

from modules.bulk.actions.send_reactions import (
    SendReactionsPayload,
    _parse_post_url,
)


def test_parse_public_post_url():
    channel, msg_id = _parse_post_url("https://t.me/durov/123")
    assert channel == "durov"
    assert msg_id == 123


def test_parse_public_with_at_prefix_ok():
    # Наш strip_url убирает t.me/, потом public_ref уберёт '@'.
    channel, msg_id = _parse_post_url("t.me/@durov/45")
    assert channel == "durov"
    assert msg_id == 45


def test_parse_private_post_url():
    channel, msg_id = _parse_post_url("https://t.me/c/1234567890/78")
    assert channel == 1234567890
    assert msg_id == 78


def test_payload_rejects_bad_url():
    with pytest.raises(Exception):
        SendReactionsPayload(post_urls=["https://t.me/nomessageid"], emojis=["👍"])


def test_payload_rejects_bad_msg_id():
    with pytest.raises(Exception):
        SendReactionsPayload(post_urls=["https://t.me/foo/notanumber"], emojis=["👍"])


def test_payload_valid_multiple():
    p = SendReactionsPayload(
        post_urls=["https://t.me/foo/1", "https://t.me/c/999/2"],
        emojis=["👍", "❤️"],
        as_big=True,
    )
    assert len(p.post_urls) == 2
    assert p.as_big is True


def test_action_registered_and_uses_reaction_governor():
    from core.enums import BulkActionType
    from modules.bulk.actions import ACTION_REGISTRY

    action = ACTION_REGISTRY[BulkActionType.SEND_REACTIONS.value]
    assert action.requires_client is True
    assert action.governor_key == "bulk_reaction"


def test_telegram_refs_reused_by_commenting():
    """После рефакторинга (backlog #1) commenting импортирует helper'ы из
    worker.telegram_refs — а не держит локальные копии."""
    import modules.commenting.worker.channels as ch
    from worker import telegram_refs

    # Убеждаемся, что локальные _strip_url и др. это те же самые объекты.
    assert ch._strip_url is telegram_refs.strip_url
    assert ch._folder_slug is telegram_refs.folder_slug
    assert ch._invite_hash is telegram_refs.invite_hash
    assert ch._public_ref is telegram_refs.public_ref
