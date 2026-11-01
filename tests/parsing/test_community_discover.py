"""Discovery сообществ: авто-ключевик из сидов + диагностика в логе."""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.parsing.parser.community_discover import (
    _derive_term,
    discover_communities,
)
from modules.parsing.repositories import ParsedCommunityItemRepository

pytestmark = pytest.mark.asyncio

_PHONE = itertools.count(91_200_000_000)


def _acc(session) -> Account:
    a = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(a); session.flush(); session.commit()
    return a


def _factory(session):
    class _Ctx:
        def __enter__(self_inner): return session
        def __exit__(self_inner, *_): return False
    return lambda: _Ctx()


def _chan(cid, title, username):
    return SimpleNamespace(
        id=cid, title=title, username=username, megagroup=False,
        access_hash=cid, verified=False, scam=False, fake=False,
        participants_count=1000, noforwards=False,
    )


class _Progress:
    def __init__(self): self.logs: list[str] = []
    def log(self, msg): self.logs.append(msg)
    def set_counts(self, **_): pass
    async def heartbeat(self, **_): pass


class _Client:
    """Мок: seed резолвится, рекомендации отдают один новый канал."""

    def __init__(self, seed, rec):
        self._seed = seed
        self._rec = rec
        self.search_terms: list[str] = []

    async def get_entity(self, _ref):
        return self._seed

    async def get_messages(self, *_a, **_k):
        return []

    async def __call__(self, request):
        name = type(request).__name__
        if name == "GetChannelRecommendationsRequest":
            return SimpleNamespace(chats=[self._rec])
        if "Search" in name:
            self.search_terms.append(getattr(request, "q", None))
            return SimpleNamespace(chats=[])
        raise RuntimeError("full chat unavailable")  # ловится в snapshot


def test_derive_term_picks_first_meaningful_word():
    e1 = SimpleNamespace(title="🔥 | Сервис")
    e2 = SimpleNamespace(title="Спорт-Экспресс")
    assert _derive_term([e1, e2]) == "Сервис"
    assert _derive_term([SimpleNamespace(title="🔥")]) is None


async def test_discovery_derives_term_and_adds_recommendations(session) -> None:
    collector = _acc(session)
    seed = _chan(1001, "Спорт-Экспресс", "sportexpress")
    rec = _chan(2002, "Спорт Шрёдингера", "sportilinet")
    client = _Client(seed, rec)
    progress = _Progress()
    ctx = {
        "session_factory": _factory(session),
        "client_pool": SimpleNamespace(get=AsyncMock(return_value=client),
                                       release=AsyncMock()),
        "governor": SimpleNamespace(check_and_reserve=AsyncMock(return_value=True)),
        "now": datetime.now(timezone.utc),
        "parsing_progress": progress,
    }

    result = await discover_communities(
        ctx, owner_user_id=7, name="спорт",
        collector_account_id=collector.id, seeds=["@sportexpress"],
        term=None, use_search=True, use_recommendations=True,
    )

    assert result is not None
    # Ключевик не задан → выведен из названия сида и ушёл в глобальный поиск.
    assert client.search_terms == ["Спорт"]
    # Рекомендация добавлена сверх сида → в списке оба канала.
    items = ParsedCommunityItemRepository(session).list_by_list(result.list_id)
    assert {getattr(i, "channel_tg_id", None) for i in items} == {1001, 2002}
    # В логе видно и вывод ключевика, и факт находки.
    joined = " | ".join(progress.logs)
    assert "Спорт" in joined
    assert any("Похожие каналы: +" in m for m in progress.logs)
