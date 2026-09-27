"""Промпт 3.2b: filters переехали в modules.parsing — smoke."""

from __future__ import annotations

from unittest.mock import MagicMock

from modules.parsing.parser.filters import (
    FilterOptions,
    REASON_BLACKLISTED,
    REASON_BOT,
    REASON_NO_USERNAME,
    apply_filters,
)


def _row(**over):
    base = {
        "tg_user_id": 1, "username": "alice", "phone": None,
        "has_premium": True, "is_bot": False, "is_deleted": False,
        "is_admin": False, "last_seen_bucket": "recently",
    }
    base.update(over)
    return base


def test_apply_filters_default_drops_bots_and_deleted() -> None:
    rows = [_row(tg_user_id=1), _row(tg_user_id=2, is_bot=True)]
    out = apply_filters(rows, options=FilterOptions())
    assert [r["tg_user_id"] for r in out.kept] == [1]
    assert out.breakdown == {REASON_BOT: 1}


def test_apply_filters_first_reason_wins() -> None:
    bl = MagicMock()
    bl.match.return_value = "hit"
    rows = [_row(is_bot=True)]
    out = apply_filters(
        rows,
        options=FilterOptions(exclude_bots=True, check_blacklist=True),
        blacklist_repo=bl,
    )
    assert out.kept == []
    assert out.breakdown == {REASON_BOT: 1}
    bl.match.assert_not_called()


def test_apply_filters_require_username_and_blacklist() -> None:
    bl = MagicMock()
    bl.match.side_effect = lambda **kw: "hit" if kw.get("tg_user_id") == 99 else None
    rows = [
        _row(tg_user_id=1),
        _row(tg_user_id=2, username=None),
        _row(tg_user_id=99),
    ]
    out = apply_filters(
        rows,
        options=FilterOptions(require_username=True, check_blacklist=True),
        blacklist_repo=bl,
    )
    kept = {r["tg_user_id"] for r in out.kept}
    assert kept == {1}
    assert out.breakdown == {REASON_NO_USERNAME: 1, REASON_BLACKLISTED: 1}
