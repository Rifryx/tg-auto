"""Промпт 3.2: apply_filters + отдельные фильтры (оффлайн-тесты)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from modules.priming.parser.filters import (
    FilterOptions,
    REASON_ADMIN,
    REASON_BLACKLISTED,
    REASON_BOT,
    REASON_DELETED,
    REASON_NOT_PREMIUM,
    REASON_NO_USERNAME,
    apply_filters,
    filter_admins,
    filter_bots,
    filter_deleted,
    filter_premium,
    filter_username,
)


def _row(**over):
    base = {
        "tg_user_id": 1,
        "username": "alice",
        "phone": None,
        "has_premium": True,
        "is_bot": False,
        "is_deleted": False,
        "is_admin": False,
        "last_seen_bucket": "recently",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Отдельные фильтры (генераторы)
# ---------------------------------------------------------------------------


def test_filter_username_drops_missing() -> None:
    out = list(filter_username([_row(username=None), _row(username="bob")]))
    assert out[0] == (None, REASON_NO_USERNAME)
    assert out[1][1] is None
    assert out[1][0]["username"] == "bob"


def test_filter_premium_requires_true() -> None:
    out = list(filter_premium([_row(has_premium=None), _row(has_premium=False), _row(has_premium=True)]))
    assert [o[1] for o in out] == [REASON_NOT_PREMIUM, REASON_NOT_PREMIUM, None]


def test_filter_bots_deleted_admins() -> None:
    assert list(filter_bots([_row(is_bot=True)]))[0][1] == REASON_BOT
    assert list(filter_deleted([_row(is_deleted=True)]))[0][1] == REASON_DELETED
    assert list(filter_admins([_row(is_admin=True)]))[0][1] == REASON_ADMIN


# ---------------------------------------------------------------------------
# apply_filters — композиция
# ---------------------------------------------------------------------------


def test_apply_filters_default_options_pass_ok_rows() -> None:
    rows = [_row(tg_user_id=1), _row(tg_user_id=2, is_bot=True), _row(tg_user_id=3, is_deleted=True)]
    out = apply_filters(rows, options=FilterOptions())
    kept_ids = {r["tg_user_id"] for r in out.kept}
    assert kept_ids == {1}
    assert out.breakdown == {REASON_BOT: 1, REASON_DELETED: 1}


def test_apply_filters_require_username() -> None:
    rows = [_row(tg_user_id=1, username=None), _row(tg_user_id=2)]
    out = apply_filters(rows, options=FilterOptions(require_username=True))
    assert [r["tg_user_id"] for r in out.kept] == [2]
    assert out.breakdown == {REASON_NO_USERNAME: 1}


def test_apply_filters_premium_only() -> None:
    rows = [_row(has_premium=True), _row(has_premium=False)]
    out = apply_filters(rows, options=FilterOptions(premium_only=True))
    assert len(out.kept) == 1
    assert out.breakdown == {REASON_NOT_PREMIUM: 1}


def test_apply_filters_first_reason_wins() -> None:
    """Строка с bot=True И blacklisted=True попадёт в breakdown как bot."""
    bl = MagicMock()
    bl.match.return_value = "hit"  # неважно что вернёт, лишь бы не None
    rows = [_row(is_bot=True, tg_user_id=42)]
    out = apply_filters(
        rows,
        options=FilterOptions(exclude_bots=True, check_blacklist=True),
        blacklist_repo=bl,
    )
    assert out.kept == []
    assert out.breakdown == {REASON_BOT: 1}
    # blacklist-репозиторий не должен быть вызван — до него не дошло.
    bl.match.assert_not_called()


def test_apply_filters_blacklist() -> None:
    """Blacklist срабатывает после локальных фильтров."""
    bl = MagicMock()
    def _match(**kw):
        return "hit" if kw.get("tg_user_id") == 99 else None
    bl.match.side_effect = _match
    rows = [_row(tg_user_id=1), _row(tg_user_id=99)]
    out = apply_filters(
        rows,
        options=FilterOptions(check_blacklist=True),
        blacklist_repo=bl,
    )
    assert [r["tg_user_id"] for r in out.kept] == [1]
    assert out.breakdown == {REASON_BLACKLISTED: 1}


def test_apply_filters_all_off_keeps_everything() -> None:
    rows = [_row(is_bot=True, is_deleted=True, is_admin=True, username=None)]
    out = apply_filters(
        rows,
        options=FilterOptions(
            require_username=False,
            premium_only=False,
            exclude_bots=False,
            exclude_deleted=False,
            exclude_admins=False,
            check_blacklist=False,
        ),
    )
    assert len(out.kept) == 1
    assert out.breakdown == {}
