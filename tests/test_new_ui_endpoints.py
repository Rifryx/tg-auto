"""API-тесты новых эндпоинтов UI-правок (bot-ui-logic-fixes).

* ``GET /accounts/check-phone`` — pre-check занятости номера до отправки SMS;
* ``GET /profile-assets/{id}/blob`` — байты аватара для превью-галереи.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.models import Account, ProfileAsset
from core.repositories.profile_asset import ProfileAssetRepository


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _clean(session):
    session.execute(
        text(
            "TRUNCATE profile_assets, account_status_history, accounts "
            "RESTART IDENTITY CASCADE"
        )
    )
    session.commit()


def _accounts_client(session, user="u1"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.deps.auth import require_user
    from api.deps.db import get_session
    from api.routers.accounts import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


def _assets_client(session, user="u1"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.deps.auth import require_user
    from api.deps.db import get_session
    from api.routers.profile_assets import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


def _make_account(session, phone):
    a = Account(
        phone=phone, session_enc=b"e", status="pool",
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    session.flush()
    session.commit()
    return a


def test_check_phone_reports_existence_and_normalizes(session):
    _clean(session)
    _make_account(session, "+380123456789")
    client = _accounts_client(session)

    # Разный формат — тот же нормализованный номер, exists=True.
    r = client.get("/accounts/check-phone", params={"phone": "380 123 456 789"})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["normalized"] == "+380123456789"

    # Свободный номер.
    r2 = client.get("/accounts/check-phone", params={"phone": "+10000000"})
    assert r2.status_code == 200
    assert r2.json()["exists"] is False


def test_check_phone_not_shadowed_by_account_id_route(session):
    _clean(session)
    client = _accounts_client(session)
    # «check-phone» не должен попасть в /{account_id} (иначе 422 на int).
    r = client.get("/accounts/check-phone", params={"phone": ""})
    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_profile_asset_blob_returns_bytes(session):
    _clean(session)
    repo = ProfileAssetRepository(session)
    asset = repo.create(
        user_id="u1", kind="avatar", binary=b"\xff\xd8\xff-jpeg", mime="image/jpeg"
    )
    session.commit()

    client = _assets_client(session)
    r = client.get(f"/profile-assets/{asset.id}/blob")
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff-jpeg"
    assert r.headers["content-type"].startswith("image/jpeg")


def test_profile_asset_blob_404_for_text_asset_and_foreign_owner(session):
    _clean(session)
    repo = ProfileAssetRepository(session)
    text_asset = repo.create(user_id="u1", kind="first_name", value="Иван")
    img = repo.create(user_id="u1", kind="avatar", binary=b"img", mime="image/png")
    session.commit()

    client = _assets_client(session, user="u1")
    # Текстовый ассет не имеет binary → 404.
    assert client.get(f"/profile-assets/{text_asset.id}/blob").status_code == 404

    # Чужой пользователь не получает байты.
    other = _assets_client(session, user="u2")
    assert other.get(f"/profile-assets/{img.id}/blob").status_code == 404
