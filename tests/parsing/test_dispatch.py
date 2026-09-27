"""Промпт 3.3: arq-хендлер parser_run диспатчит по kind."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")


pytestmark = pytest.mark.asyncio


PAYLOAD = {
    "owner_user_id": 1, "name": "n",
    "collector_account_id": 42, "chat_ref": "@x",
    "days_window": 7, "min_messages": 2,
    "require_username": True, "premium_only": False,
}


async def test_dispatch_chat_messages() -> None:
    from modules.parsing.worker.dispatch import parser_run
    from modules.parsing.parser.chat_messages import ParseResult

    async def _fake(ctx, **kwargs):
        # Проверяем, что filter_options пробрасывается со значениями payload.
        opts = kwargs["filter_options"]
        assert opts.require_username is True
        assert opts.premium_only is False
        return ParseResult(list_id=7, raw_count=10, inserted=5,
                           filters_breakdown={"bot": 2})

    with patch("modules.parsing.worker.dispatch.parse_chat_messages", side_effect=_fake) as m:
        result = await parser_run({"ctx": True}, "chat_messages", PAYLOAD)
        m.assert_awaited_once()
    assert result == {
        "list_id": 7, "raw_count": 10, "inserted": 5,
        "filters_breakdown": {"bot": 2},
    }


async def test_dispatch_chat_members() -> None:
    from modules.parsing.worker.dispatch import parser_run
    from modules.parsing.parser.chat_members import ParseResult

    async def _fake(ctx, **kwargs):
        assert kwargs["only_recently_seen"] is True
        return ParseResult(list_id=1, raw_count=3, inserted=2,
                           filters_breakdown={})

    with patch(
        "modules.parsing.worker.dispatch.parse_chat_members", side_effect=_fake,
    ):
        payload = {**PAYLOAD, "only_recently_seen": True}
        result = await parser_run({}, "chat_members", payload)
    assert result["list_id"] == 1
    assert result["inserted"] == 2


async def test_dispatch_unknown_kind_returns_error() -> None:
    from modules.parsing.worker.dispatch import parser_run

    result = await parser_run({}, "wat", PAYLOAD)
    assert "unknown kind" in result["error"]


async def test_dispatch_skipped_when_parser_returns_none() -> None:
    from modules.parsing.worker.dispatch import parser_run

    async def _fake(ctx, **_kw): return None

    with patch("modules.parsing.worker.dispatch.parse_chat_messages", side_effect=_fake):
        result = await parser_run({}, "chat_messages", PAYLOAD)
    assert result == {"skipped": True}
