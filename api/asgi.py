"""Продовый ASGI-entrypoint API-слоя (PROJECT-STAGES §4/§6; аудит #5).

``create_app()`` собирает FastAPI-приложение целиком: роутеры, CORS, request-id,
глобальный обработчик ошибок и lifespan с fail-fast проверкой коннектов к
Postgres и Redis. Модульный ``app = create_app()`` — цель для gunicorn/uvicorn::

    gunicorn -c deploy/gunicorn.conf.py api.asgi:app
    uvicorn api.asgi:app

Все «кирпичи» вынесены отдельными функциями/классами (``RequestIDMiddleware``,
``make_internal_error_handler``, ``verify_connectivity`` …), чтобы их можно было
тестировать в изоляции, без поднятия всего приложения.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, Optional

import redis
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from starlette.datastructures import MutableHeaders

from core.config import Settings, get_settings
from worker.tasks.logging import configure_logging, get_logger

REQUEST_ID_HEADER = "X-Request-ID"
# Таймауты коннекта — чтобы startup падал быстро, а не висел бесконечно.
_CONNECT_TIMEOUT_SEC = 3


# --- request-id --------------------------------------------------------------


class RequestIDMiddleware:
    """Чистый ASGI-middleware: uuid на запрос → structlog contextvars + заголовок.

    Реализован как ASGI (не BaseHTTPMiddleware), чтобы contextvars, привязанные
    перед вызовом приложения, были видны обработчику в ТОМ ЖЕ контексте.
    ``request_id`` дополнительно кладётся в ``scope['state']`` — оттуда его берёт
    обработчик ошибок (contextvars к тому моменту уже отвязаны).
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message.setdefault("headers", []))
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")


def _request_id_of(request: Request) -> str:
    """Достаёт request_id из scope['state'] (fallback — из contextvars)."""
    rid = getattr(request.state, "request_id", None)
    if rid:
        return rid
    return structlog.contextvars.get_contextvars().get("request_id", "unknown")


# --- глобальный обработчик ошибок --------------------------------------------


def make_internal_error_handler(
    dev_mode: bool,
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    """Хендлер неотловленных исключений: 500 + {error, request_id}, без стектрейса.

    Стектрейс уходит ТОЛЬКО в лог; в тело ответа он не попадает (кроме DEV_MODE,
    где добавляется поле ``detail`` для отладки).
    """

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id_of(request)
        get_logger().error(
            "api.unhandled_exception",
            request_id=request_id,
            path=request.url.path,
            method=request.method,
            exc_info=exc,
        )
        body: dict[str, Any] = {"error": "internal_error", "request_id": request_id}
        if dev_mode:
            body["detail"] = repr(exc)
        return JSONResponse(
            status_code=500,
            content=body,
            headers={REQUEST_ID_HEADER: request_id},
        )

    return handler


# --- коннективность (fail fast) ----------------------------------------------


def verify_connectivity(engine: Any, redis_client: Any) -> None:
    """Проверяет Postgres (SELECT 1) и Redis (PING); при сбое — RuntimeError.

    Понятное сообщение об ошибке + лог; наружу пробрасывается ``RuntimeError``,
    чтобы старт упал быстро и явно, а не завис.
    """
    log = get_logger()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        log.error("api.startup.postgres_unavailable", error=repr(exc))
        raise RuntimeError(f"Postgres is unavailable at startup: {exc!r}") from exc
    try:
        redis_client.ping()
    except Exception as exc:  # noqa: BLE001
        log.error("api.startup.redis_unavailable", error=repr(exc))
        raise RuntimeError(f"Redis is unavailable at startup: {exc!r}") from exc
    log.info("api.startup.connectivity_ok")


def _make_engine(settings: Settings):
    return create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT_SEC},
    )


def _make_redis(settings: Settings) -> redis.Redis:
    return redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=_CONNECT_TIMEOUT_SEC,
        socket_timeout=_CONNECT_TIMEOUT_SEC,
    )


def _build_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = _make_engine(settings)
        redis_client = _make_redis(settings)
        # fail fast: если Postgres/Redis недоступны — старт падает с понятным логом.
        verify_connectivity(engine, redis_client)
        app.state.db_engine = engine
        app.state.redis = redis_client
        try:
            yield
        finally:
            engine.dispose()
            try:
                redis_client.close()
            except Exception:  # noqa: BLE001 - закрытие не должно ронять shutdown
                pass

    return lifespan


# --- сборка приложения -------------------------------------------------------


def install_middlewares(app: FastAPI, settings: Settings) -> None:
    """CORS (origin Mini App / всё в DEV) + request-id. Порядок важен.

    ``add_middleware`` кладёт последний добавленный НАРУЖУ, поэтому request-id
    добавляем последним — он оборачивает всё, и заголовок/контекст есть даже для
    CORS-ответов.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestIDMiddleware)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()

    # Импорт роутеров здесь (не на уровне модуля): фабрику можно частично
    # переиспользовать/тестировать, не таща весь граф на импорте asgi.
    from api.routers import accounts, admin, billing, login, monitoring, personas, proxies
    from modules.commenting.api import router as commenting_router
    from modules.commenting.api.channels import router as channels_router

    app = FastAPI(
        title="Neuro-commenting API",
        version="0.1.0",
        description="Shared REST API: аккаунты, прокси, персоны (Telegram Mini App).",
        lifespan=_build_lifespan(settings),
    )

    install_middlewares(app, settings)
    app.add_exception_handler(Exception, make_internal_error_handler(settings.dev_mode))

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(accounts.router)
    app.include_router(login.router)
    app.include_router(monitoring.router)
    app.include_router(proxies.router)
    app.include_router(personas.router)
    app.include_router(billing.router)
    app.include_router(admin.router)
    app.include_router(commenting_router)
    app.include_router(channels_router)
    return app


# ``app`` строится ЛЕНИВО (PEP 562): ``gunicorn api.asgi:app`` / ``uvicorn
# api.asgi:app`` резолвят атрибут через getattr → приложение собирается только
# при реальном запуске сервера (и требует ENV: ENCRYPTION_KEY и т.д.). Импорт
# самого модуля (например, отдельных «кирпичей» в тестах) app НЕ поднимает.
_app: Optional[FastAPI] = None


def __getattr__(name: str) -> Any:
    if name == "app":
        global _app
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
