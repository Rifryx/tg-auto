"""Юнит-тесты чистых парсеров Telegram-ссылок (worker/telegram_refs.py).

Без сети, без БД, без Telethon.
"""

from __future__ import annotations

from worker.telegram_refs import (
    classify_ref,
    folder_slug,
    invite_hash,
    public_ref,
    strip_url,
)


def test_strip_url_handles_scheme_and_hosts():
    assert strip_url("https://t.me/foo") == "foo"
    assert strip_url("http://t.me/foo/") == "foo"
    assert strip_url("telegram.me/foo") == "foo"
    assert strip_url("  @foo ") == "@foo"


def test_public_ref_strips_at_sign():
    assert public_ref("@foo") == "foo"
    assert public_ref("https://t.me/foo") == "foo"


def test_folder_slug_detects_addlist():
    assert folder_slug("https://t.me/addlist/abc123") == "abc123"
    assert folder_slug("t.me/addlist/x") == "x"
    assert folder_slug("t.me/foo") is None


def test_invite_hash_detects_plus_and_joinchat():
    assert invite_hash("https://t.me/+abcXYZ") == "abcXYZ"
    assert invite_hash("t.me/joinchat/xxx") == "xxx"
    assert invite_hash("t.me/foo") is None


def test_classify_ref_dispatches_correctly():
    assert classify_ref("@foo") == "public"
    assert classify_ref("https://t.me/+xxx") == "invite"
    assert classify_ref("https://t.me/addlist/slug") == "folder"


def test_edge_cases_return_none_not_empty_string():
    assert folder_slug("t.me/addlist/") is None
    assert invite_hash("t.me/+") is None
    assert invite_hash("t.me/joinchat/") is None
