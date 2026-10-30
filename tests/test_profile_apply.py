"""Интеграционные тесты worker/profiles/apply.py (этап 6 УТП).

Telethon не поднимается — fake-клиент возвращает нужные ответы или бросает
специфичные ошибки. Проверяем:
* UpdateProfileRequest вызван c именно теми аргументами;
* username-коллизия перебирает кандидатов;
* apply_profile bulk-action синхронизирует нашу БД с реально применённым.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from telethon.errors import UsernameOccupiedError
from telethon.tl.functions.account import (
    UpdateProfileRequest,
    UpdateUsernameRequest,
)

from core.models import Account
from core.repositories.account import AccountRepository
from worker.profiles.apply import apply_profile_to_telegram

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

_TABLES = (
    "bulk_job_items",
    "bulk_jobs",
    "accounts",
    "proxies",
    "health_events",
    "account_health",
    "account_status_history",
    "warming_activities",
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)
_PHONE = iter(range(50_000_000_000, 50_001_000_000))


class _Req:
    pass


class _FakeClient:
    """Ловит .__call__(request); сценарий реакций задаётся snapshot'ом."""

    def __init__(self, *, occupied: set[str] | None = None):
        self.calls: list[object] = []
        self._occupied = occupied or set()

    async def __call__(self, request):
        self.calls.append(request)
        if isinstance(request, UpdateUsernameRequest):
            if request.username in self._occupied:
                raise UsernameOccupiedError(request=_Req())
            return True
        # UpdateProfileRequest → отдаём успех.
        return True


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _make_account(session) -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status="pool",
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc.id


async def test_apply_profile_updates_name_and_bio(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()

    result = await apply_profile_to_telegram(
        client,
        account_id=account_id,
        session_factory=_factory(session),
        first_name="Никита",
        last_name="Ковалёв",
        bio="short bio",
    )

    assert result.updated_names is True
    assert result.updated_bio is True
    assert result.applied_username is None
    # Один вызов UpdateProfileRequest с ожидаемыми полями.
    assert len(client.calls) == 1
    req = client.calls[0]
    assert isinstance(req, UpdateProfileRequest)
    assert req.first_name == "Никита"
    assert req.last_name == "Ковалёв"
    assert req.about == "short bio"


async def test_apply_profile_iterates_username_candidates_on_conflict(session):
    _clean(session)
    account_id = _make_account(session)
    # Первый занят, второй свободен — берём второй.
    client = _FakeClient(occupied={"nick_dev"})

    result = await apply_profile_to_telegram(
        client,
        account_id=account_id,
        session_factory=_factory(session),
        username_candidates=["nick_dev", "kv_ski"],
    )
    assert result.applied_username == "kv_ski"
    assert result.tried_usernames == ["nick_dev", "kv_ski"]
    assert result.errors.get("nick_dev") == "UsernameOccupiedError"


async def test_apply_profile_gives_up_when_all_candidates_taken(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient(occupied={"a_dev", "b_dev"})

    result = await apply_profile_to_telegram(
        client,
        account_id=account_id,
        session_factory=_factory(session),
        username_candidates=["a_dev", "b_dev"],
    )
    assert result.applied_username is None
    assert len(result.errors) == 2


async def test_apply_profile_action_picks_fallback_variant(session):
    """apply_profile: все переданные кандидаты заняты → экшн подбирает
    свободный алгоритмический вариант (auto_username_variants)."""
    from core.enums import BulkActionType
    from modules.bulk.actions import ACTION_REGISTRY
    from modules.bulk.actions.apply_profile import ApplyProfilePayload

    _clean(session)
    account_id = _make_account(session)
    # Оба запрошенных заняты; алгоритмические варианты (anutka<digits>) свободны.
    client = _FakeClient(occupied={"anutka", "anutka_official"})

    action = ACTION_REGISTRY[BulkActionType.APPLY_PROFILE.value]
    payload = ApplyProfilePayload(
        first_name="Anna",
        username_candidates=["anutka", "anutka_official"],
    )
    result = await action.run(
        account_id=account_id,
        payload=payload,
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.ok is True
    applied = result.detail["applied_username"]
    assert applied is not None
    assert applied not in {"anutka", "anutka_official"}
    # В БД записан подобранный username.
    session.expire_all()
    assert AccountRepository(session).get(account_id).username == applied


async def test_apply_profile_noop_when_all_fields_none(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()
    result = await apply_profile_to_telegram(
        client,
        account_id=account_id,
        session_factory=_factory(session),
    )
    assert result.updated_names is False
    assert result.updated_bio is False
    assert result.applied_username is None
    assert client.calls == []


async def test_generate_and_apply_uses_prompt_without_persona(session):
    """«Профиль ИИ» по промпту: персона не обязательна, генерим по описанию."""
    from types import SimpleNamespace

    from core.enums import BulkActionType
    from modules.bulk.actions import ACTION_REGISTRY
    from modules.bulk.actions.generate_and_apply_profile import (
        GenerateAndApplyPayload,
    )

    _clean(session)
    account_id = _make_account(session)  # без персоны
    client = _FakeClient()

    class _Gen:
        async def generate_from_prompt(self, prompt):
            assert prompt == "крипто-трейдер"
            return SimpleNamespace(
                first_name="Иван", last_name="Петров", bio="trader",
                username_candidates=["ivan_t"],
                as_dict=lambda: {"first_name": "Иван"},
            )

        async def generate(self, persona):  # не должен вызываться
            raise AssertionError("ожидали генерацию по промпту")

    action = ACTION_REGISTRY[BulkActionType.GENERATE_AND_APPLY_PROFILE.value]
    payload = GenerateAndApplyPayload(prompt="крипто-трейдер")
    result = await action.run(
        account_id=account_id,
        payload=payload,
        session_factory=_factory(session),
        publisher=None,
        client=client,
        generator=_Gen(),
    )
    assert result.ok is True
    assert result.skipped is False  # нет персоны, но не пропущено — по промпту
