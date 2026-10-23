"""Поддержка: тред сообщений, отправка, релеи ответов менеджера."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_publisher
from api.routers import app_content as content_router
from core.repositories.app_user import AppUserRepository
from core.repositories.support import SupportRepository


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, channel, payload):
        self.published.append((channel, dict(payload)))


def _app(session, publisher=None):
    app = FastAPI()
    app.include_router(content_router.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: "777"
    app.dependency_overrides[get_publisher] = lambda: publisher
    return app


def test_support_send_and_thread(session):
    pub = _FakePublisher()
    # Профиль пользователя — чтобы менеджер видел @username + имя.
    AppUserRepository(session).upsert(
        "777", username="bob", first_name="Bob", last_name="Smith"
    )
    session.commit()

    client = TestClient(_app(session, pub))

    r = client.post("/app/support/messages", json={"text": "Помогите!"})
    assert r.status_code == 200, r.text
    assert r.json()["direction"] == "user"

    # Опубликовано боту со всем профилем — чтобы менеджер видел, кто пишет
    # (не только числовой user_id).
    assert pub.published and pub.published[0][0] == "support.new_message"
    sent = pub.published[0][1]
    assert sent["username"] == "bob"
    assert sent["first_name"] == "Bob"
    assert sent["last_name"] == "Smith"
    assert sent["user_id"] == "777"

    # Тред содержит сообщение.
    t = client.get("/app/support/messages")
    assert t.status_code == 200
    msgs = t.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["text"] == "Помогите!"


def test_manager_reply_routes_back_via_relay(session):
    """Релей (chat_id, message_id) → user_id; ответ менеджера виден в треде."""
    repo = SupportRepository(session)
    repo.add_message(user_id="777", direction="user", text="Вопрос", username="bob")
    repo.add_relay(chat_id="999", message_id=42, user_id="777")
    session.commit()

    # Менеджер ответил реплаем на сообщение 42 в чате 999.
    found = repo.user_for_relay(chat_id="999", message_id=42)
    assert found == "777"
    repo.add_message(user_id=found, direction="manager", text="Ответ менеджера")
    session.commit()

    client = TestClient(_app(session))
    msgs = client.get("/app/support/messages").json()["messages"]
    assert [m["direction"] for m in msgs] == ["user", "manager"]
    assert msgs[1]["text"] == "Ответ менеджера"


def test_send_publish_failure_still_stores(session):
    """Если публикация боту падает (Redis недоступен) — сообщение всё равно
    сохранено, пользователь видит его в треде."""

    class _Boom:
        def publish(self, *_a, **_k):
            raise RuntimeError("redis down")

    client = TestClient(_app(session, _Boom()))
    r = client.post("/app/support/messages", json={"text": "hi"})
    assert r.status_code == 200
    assert len(client.get("/app/support/messages").json()["messages"]) == 1


def test_purge_older_than(session):
    from datetime import datetime, timedelta, timezone

    from core.models.support import SupportMessage

    repo = SupportRepository(session)
    old = SupportMessage(
        user_id="777", direction="user", text="old",
        created_at=datetime.now(timezone.utc) - timedelta(days=40),
    )
    session.add(old)
    repo.add_message(user_id="777", direction="user", text="new")
    session.commit()

    removed = repo.purge_older_than(30)
    session.commit()
    assert removed == 1
    remaining = repo.thread("777")
    assert [m.text for m in remaining] == ["new"]
