"""Живой прогресс/управление парсингом: parsing.jobs + dispatch + progress."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("telethon")

from modules.parsing.parser.chat_members import ParseResult
from modules.parsing.repositories import ParsingJobRepository
from modules.parsing.worker.progress import ParsingProgress, ParsingStopped

pytestmark = pytest.mark.asyncio


class _Ctx:
    def __init__(self, s):
        self._s = s

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


def _factory(session):
    return lambda: _Ctx(session)


async def test_job_lifecycle_done(session):
    repo = ParsingJobRepository(session)
    job = repo.create(owner_user_id=1, kind="chat_members", name="L", params={})
    session.commit()

    async def _fake(ctx, **_kw):
        # Прогресс доступен парсеру через ctx.
        assert ctx.get("parsing_progress") is not None
        # Governor обязательно доступен в ctx: парсеры дёргают ctx["governor"]
        # напрямую без собственного фолбэка. Регрессия на реальный баг — пустой
        # ctx без redis падал KeyError('governor') на запуске (видно в UI как
        # «✖ Ошибка: KeyError('governor')»).
        assert ctx.get("governor") is not None
        return ParseResult(list_id=99, raw_count=20, inserted=8, filters_breakdown={})

    from modules.parsing.worker.dispatch import parser_run

    with patch("modules.parsing.worker.dispatch.parse_chat_members", side_effect=_fake):
        result = await parser_run(
            {"session_factory": _factory(session)},
            "chat_members",
            {"job_id": job.id, "owner_user_id": 1, "name": "L",
             "collector_account_id": 1, "chat_ref": "@x", "only_recently_seen": True},
        )
    assert result["list_id"] == 99
    session.expire_all()
    got = repo.get(job.id)
    assert got.status == "done"
    assert got.list_id == 99
    assert got.raw_count == 20
    assert got.inserted_count == 8
    assert any("Готово" in line["msg"] for line in got.log)


async def test_job_stop_before_start(session):
    repo = ParsingJobRepository(session)
    job = repo.create(owner_user_id=1, kind="chat_members", name="L", params={})
    repo.set_control(job.id, "stop")
    session.commit()

    from modules.parsing.worker.dispatch import parser_run

    called = False

    async def _fake(ctx, **_kw):
        nonlocal called
        called = True
        return ParseResult(list_id=1, raw_count=0, inserted=0, filters_breakdown={})

    with patch("modules.parsing.worker.dispatch.parse_chat_members", side_effect=_fake):
        result = await parser_run(
            {"session_factory": _factory(session)},
            "chat_members",
            {"job_id": job.id, "owner_user_id": 1, "name": "L",
             "collector_account_id": 1, "chat_ref": "@x"},
        )
    assert result == {"stopped": True}
    assert called is False
    session.expire_all()
    assert repo.get(job.id).status == "stopped"


async def test_job_failed_records_error(session):
    repo = ParsingJobRepository(session)
    job = repo.create(owner_user_id=1, kind="chat_members", name="L", params={})
    session.commit()

    async def _boom(ctx, **_kw):
        raise RuntimeError("telethon exploded")

    from modules.parsing.worker.dispatch import parser_run

    with patch("modules.parsing.worker.dispatch.parse_chat_members", side_effect=_boom):
        result = await parser_run(
            {"session_factory": _factory(session)},
            "chat_members",
            {"job_id": job.id, "owner_user_id": 1, "name": "L",
             "collector_account_id": 1, "chat_ref": "@x"},
        )
    assert "telethon exploded" in result["error"]
    session.expire_all()
    got = repo.get(job.id)
    assert got.status == "failed"
    assert "telethon exploded" in (got.error or "")


async def test_progress_heartbeat_stop_raises(session):
    repo = ParsingJobRepository(session)
    job = repo.create(owner_user_id=1, kind="chat_members", name="L", params={})
    session.commit()

    progress = ParsingProgress(_factory(session), job.id)
    # Контроль = run → heartbeat проходит.
    await progress.heartbeat(raw=5)
    session.expire_all()
    assert repo.get(job.id).raw_count == 5

    # Контроль = stop → heartbeat бросает ParsingStopped.
    repo.set_control(job.id, "stop")
    session.commit()
    with pytest.raises(ParsingStopped):
        await progress.heartbeat(raw=10)


async def test_run_endpoint_creates_job_and_control(session):
    """POST run создаёт parsing.job; control pause/stop меняют флаг/статус."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.deps.auth import require_user
    from api.deps.db import get_session
    from api.deps.queue import get_task_queue
    from modules.parsing.api.router import router

    enqueued: list = []

    class _FakeQueue:
        async def enqueue(self, task_name, *args, **kwargs):
            enqueued.append((task_name, args))
            return "arq-1"

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: "1"
    app.dependency_overrides[get_task_queue] = lambda: _FakeQueue()
    client = TestClient(app)

    r = client.post(
        "/modules/parsing/lists/run/chat-members",
        json={"name": "L", "collector_account_id": 5, "chat_ref": "@x"},
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    assert isinstance(job_id, int)
    # Воркеру ушёл job_id в payload.
    assert enqueued and enqueued[0][1][1]["job_id"] == job_id

    # Задача видна и поллится.
    g = client.get(f"/modules/parsing/jobs/{job_id}")
    assert g.status_code == 200
    assert g.json()["status"] == "pending"

    # Пауза → control=pause.
    p = client.post(f"/modules/parsing/jobs/{job_id}/control", json={"action": "pause"})
    assert p.status_code == 200
    assert p.json()["control"] == "pause"

    # Стоп → control=stop.
    s = client.post(f"/modules/parsing/jobs/{job_id}/control", json={"action": "stop"})
    assert s.status_code == 200
    assert s.json()["control"] == "stop"

    # Неизвестное действие → 422.
    bad = client.post(f"/modules/parsing/jobs/{job_id}/control", json={"action": "x"})
    assert bad.status_code == 422


def test_control_action_pause_resume(session):
    repo = ParsingJobRepository(session)
    job = repo.create(owner_user_id=1, kind="chat_members", name="L", params={})
    repo.set_status(job.id, "running")
    session.commit()

    repo.set_control(job.id, "pause")
    session.commit()
    session.expire_all()
    assert repo.get(job.id).status == "paused"

    repo.set_control(job.id, "run")
    session.commit()
    session.expire_all()
    assert repo.get(job.id).status == "running"
