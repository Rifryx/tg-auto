"""Тесты кросс-модульного blacklist'а (prompt 7.1).

Не тянем БД: подменяем ``session.execute`` на stub, который смотрит на
переданные параметры (cutoff, owner, tg/username/phone) и решает,
вернуть ли строку. Так проверяем контракт ``match_cross_module``:
* окно ``window_days`` действительно передаётся как cutoff;
* ключи фильтров передаются как есть;
* без ключа match_cross_module возвращает None и SQL не вызывается.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from modules.priming.repositories.blacklist import (
    CROSS_MODULE_WINDOW_DAYS,
    BlacklistRepository,
)


@dataclass
class _Result:
    row: Optional[dict]

    def mappings(self):
        return self

    def first(self):
        return self.row


class _StubSession:
    def __init__(self, *, respond_with: Optional[dict] = None) -> None:
        self.respond_with = respond_with
        self.last_params: Optional[dict] = None
        self.calls = 0

    def execute(self, stmt, params=None):  # noqa: D401 — совместимость
        self.calls += 1
        self.last_params = params
        return _Result(self.respond_with)


def _repo_with(session: _StubSession) -> BlacklistRepository:
    repo = BlacklistRepository.__new__(BlacklistRepository)
    repo.session = session  # type: ignore[attr-defined]
    return repo


def test_match_cross_module_no_keys_returns_none_and_skips_sql() -> None:
    session = _StubSession()
    repo = _repo_with(session)
    assert repo.match_cross_module(owner_user_id=1) is None
    assert session.calls == 0


def test_match_cross_module_passes_owner_and_keys_and_window() -> None:
    session = _StubSession(
        respond_with={
            "module": "priming",
            "id": 42,
            "reason": "manual",
            "added_at": datetime.now(timezone.utc),
            "tg_user_id": 100,
            "username": None,
            "phone": None,
            "owner_user_id": 1,
        }
    )
    repo = _repo_with(session)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    hit = repo.match_cross_module(
        owner_user_id=1, tg_user_id=100, window_days=3, now=now,
    )
    assert hit is not None
    assert hit["module"] == "priming"
    params = session.last_params or {}
    assert params["owner"] == 1
    assert params["tg"] == 100
    assert params["username"] is None
    assert params["phone"] is None
    assert params["cutoff"] == now - timedelta(days=3)


def test_match_cross_module_default_window() -> None:
    session = _StubSession(respond_with=None)
    repo = _repo_with(session)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    assert repo.match_cross_module(
        owner_user_id=None, username="alice", now=now,
    ) is None
    params = session.last_params or {}
    assert params["cutoff"] == now - timedelta(days=CROSS_MODULE_WINDOW_DAYS)
    assert params["username"] == "alice"
    assert params["owner"] is None
