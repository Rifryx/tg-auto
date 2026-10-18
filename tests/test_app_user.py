"""Профиль пользователя: разбор initData + upsert кэша app_users (#7)."""

from __future__ import annotations

import json

from api.deps.auth import _extract_user_profile
from core.repositories.app_user import AppUserRepository


def _fields(user: dict) -> dict:
    return {"user": json.dumps(user), "auth_date": "1"}


def test_extract_profile_full():
    p = _extract_user_profile(
        _fields({"id": 123, "username": "neo", "first_name": "Thomas", "last_name": "A"})
    )
    assert p is not None
    assert (p.user_id, p.username, p.first_name, p.last_name) == (
        "123", "neo", "Thomas", "A",
    )


def test_extract_profile_minimal_no_username():
    p = _extract_user_profile(_fields({"id": 7, "first_name": "Trinity"}))
    assert p is not None
    assert p.user_id == "7"
    assert p.username is None
    assert p.first_name == "Trinity"


def test_extract_profile_blank_username_is_none():
    p = _extract_user_profile(_fields({"id": 9, "username": "  "}))
    assert p is not None
    assert p.username is None


def test_extract_profile_no_user_field():
    assert _extract_user_profile({"auth_date": "1"}) is None


def test_upsert_inserts_then_updates(session):
    repo = AppUserRepository(session)
    repo.upsert("555", username="old", first_name="A")
    session.commit()
    session.expire_all()
    assert repo.get_many(["555"])["555"].username == "old"

    # Повторный upsert обновляет (например, пользователь сменил username).
    # expire_all — core-level upsert не трогает identity map сессии (в проде
    # каждый запрос — своя сессия, поэтому там этого не нужно).
    repo.upsert("555", username="new", first_name="A")
    session.commit()
    session.expire_all()
    assert repo.get_many(["555"])["555"].username == "new"

    session.execute(__import__("sqlalchemy").text("DELETE FROM app_users WHERE user_id='555'"))
    session.commit()
