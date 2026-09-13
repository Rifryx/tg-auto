"""Тесты прод-entrypoint API: request-id, обработчик ошибок, CORS, коннективность.

«Кирпичи» из :mod:`api.asgi` тестируются в изоляции на минимальных приложениях —
без подъёма всего графа роутеров и без реальных Postgres/Redis.
"""

from __future__ import annotations

import asyncio

import pytest
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from api.asgi import (
    REQUEST_ID_HEADER,
    RequestIDMiddleware,
    _build_lifespan,
    make_internal_error_handler,
    verify_connectivity,
)
from core.config import Settings

pytestmark = pytest.mark.filterwarnings("ignore")


# --- request-id --------------------------------------------------------------


def _request_id_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/whoami")
    def whoami() -> dict:
        # request_id, привязанный middleware к contextvars ЭТОГО запроса
        return {"ctx_request_id": structlog.contextvars.get_contextvars().get("request_id")}

    return app


def test_request_id_header_matches_context_and_is_unique():
    client = TestClient(_request_id_app())

    r1 = client.get("/whoami")
    r2 = client.get("/whoami")

    assert r1.status_code == 200
    # заголовок X-Request-ID присутствует и совпадает с id в structlog-контексте
    assert r1.headers[REQUEST_ID_HEADER] == r1.json()["ctx_request_id"]
    assert r2.headers[REQUEST_ID_HEADER] == r2.json()["ctx_request_id"]
    # разные запросы → разные id
    assert r1.headers[REQUEST_ID_HEADER] != r2.headers[REQUEST_ID_HEADER]


def test_request_id_parallel_requests_isolated():
    """Два параллельных запроса → разные id, каждый видит СВОЙ в контексте."""
    import httpx

    app = _request_id_app()

    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r1, r2 = await asyncio.gather(client.get("/whoami"), client.get("/whoami"))
        return r1, r2

    r1, r2 = asyncio.run(_run())
    # у каждого ответа id из тела == id из заголовка (контекст не «протёк» между запросами)
    assert r1.json()["ctx_request_id"] == r1.headers[REQUEST_ID_HEADER]
    assert r2.json()["ctx_request_id"] == r2.headers[REQUEST_ID_HEADER]
    assert r1.headers[REQUEST_ID_HEADER] != r2.headers[REQUEST_ID_HEADER]


# --- глобальный обработчик ошибок --------------------------------------------


def _boom_app(dev_mode: bool) -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(Exception, make_internal_error_handler(dev_mode))

    @app.get("/boom")
    def boom() -> dict:
        raise ValueError("secret-internal-detail-xyz")

    # raise_server_exceptions=False → получаем 500-ответ, а не проброс исключения
    return TestClient(app, raise_server_exceptions=False)


def test_internal_error_hides_traceback_in_prod():
    client = _boom_app(dev_mode=False)
    r = client.get("/boom")

    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "internal_error"
    assert body["request_id"] == r.headers[REQUEST_ID_HEADER]
    # ни стектрейса, ни текста исключения в теле ответа
    assert "Traceback" not in r.text
    assert "secret-internal-detail-xyz" not in r.text
    assert "detail" not in body


def test_internal_error_includes_detail_in_dev():
    client = _boom_app(dev_mode=True)
    r = client.get("/boom")

    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "internal_error"
    # в DEV_MODE — поле detail для отладки (стектрейс всё равно только в логе)
    assert "secret-internal-detail-xyz" in body["detail"]


# --- CORS --------------------------------------------------------------------


def _cors_client(origins: list[str]) -> TestClient:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_cors_blocks_disallowed_origin_in_prod():
    client = _cors_client(["https://app.example"])  # non-dev: только Mini App origin

    bad = client.get("/ping", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in bad.headers}

    good = client.get("/ping", headers={"origin": "https://app.example"})
    assert good.headers.get("access-control-allow-origin") == "https://app.example"


def test_cors_allows_everything_in_dev():
    client = _cors_client(["*"])  # DEV_MODE → cors_allow_origins == ["*"]
    r = client.get("/ping", headers={"origin": "https://anything.example"})
    assert r.headers.get("access-control-allow-origin") == "*"


def test_settings_cors_origins_by_mode():
    dev = Settings(encryption_key="k", dev_mode=True)
    assert dev.cors_allow_origins == ["*"]

    prod = Settings(
        encryption_key="k",
        dev_mode=False,
        telegram_api_id=1,
        telegram_api_hash="h",
        deepseek_api_key="key",
        webapp_origin="https://a.example, https://b.example",
    )
    assert prod.cors_allow_origins == ["https://a.example", "https://b.example"]

    prod_empty = Settings(
        encryption_key="k",
        dev_mode=False,
        telegram_api_id=1,
        telegram_api_hash="h",
        deepseek_api_key="key",
    )
    assert prod_empty.cors_allow_origins == []


# --- fail-fast коннективность (lifespan) -------------------------------------


class _OKConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, stmt):
        return None


class _OKEngine:
    def __init__(self):
        self.disposed = False

    def connect(self):
        return _OKConn()

    def dispose(self):
        self.disposed = True


class _FailEngine:
    def connect(self):
        raise OSError("postgres refused")


class _OKRedis:
    def __init__(self):
        self.closed = False

    def ping(self):
        return True

    def close(self):
        self.closed = True


class _FailRedis:
    def ping(self):
        raise OSError("redis refused")

    def close(self):
        pass


def test_verify_connectivity_ok():
    verify_connectivity(_OKEngine(), _OKRedis())  # не бросает


def test_verify_connectivity_postgres_down():
    with pytest.raises(RuntimeError, match="Postgres"):
        verify_connectivity(_FailEngine(), _OKRedis())


def test_verify_connectivity_redis_down():
    with pytest.raises(RuntimeError, match="Redis"):
        verify_connectivity(_OKEngine(), _FailRedis())


def test_lifespan_startup_fails_fast_on_redis_down(monkeypatch):
    """С недоступным Redis lifespan-startup падает RuntimeError, не зависает."""
    import api.asgi as asgi

    engine = _OKEngine()
    monkeypatch.setattr(asgi, "_make_engine", lambda s: engine)
    monkeypatch.setattr(asgi, "_make_redis", lambda s: _FailRedis())

    settings = Settings(encryption_key="k", dev_mode=True)
    lifespan = _build_lifespan(settings)
    app = FastAPI()

    async def _enter():
        async with lifespan(app):
            pass

    with pytest.raises(RuntimeError, match="Redis"):
        asyncio.run(_enter())


def test_lifespan_ok_disposes_resources(monkeypatch):
    import api.asgi as asgi

    engine = _OKEngine()
    redis_client = _OKRedis()
    monkeypatch.setattr(asgi, "_make_engine", lambda s: engine)
    monkeypatch.setattr(asgi, "_make_redis", lambda s: redis_client)

    settings = Settings(encryption_key="k", dev_mode=True)
    lifespan = _build_lifespan(settings)
    app = FastAPI()

    async def _cycle():
        async with lifespan(app):
            assert app.state.db_engine is engine
            assert app.state.redis is redis_client

    asyncio.run(_cycle())
    assert engine.disposed is True      # engine.dispose() на shutdown
    assert redis_client.closed is True  # redis.close() на shutdown
