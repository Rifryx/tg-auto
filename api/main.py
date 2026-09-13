"""FastAPI-приложение API-слоя (PROJECT-STAGES §4/§6).

Только лёгкие операции: чтение из Postgres и постановка задач воркеру через
очередь. Никакого Telethon и никакой прямой смены статуса аккаунтов.

Это «голое» приложение (без lifespan/CORS/request-id) — удобно для тестов и
локальной отладки. **Прод-entrypoint — ``api.asgi:app``** (fail-fast проверка
коннектов, CORS, request-id, глобальный обработчик ошибок), его и запускают под
gunicorn/uvicorn (см. ``deploy/gunicorn.conf.py``).
"""

from __future__ import annotations

from fastapi import FastAPI

from api.routers import accounts, login, monitoring, personas, proxies
from modules.commenting.api import router as commenting_router

app = FastAPI(
    title="Neuro-commenting API",
    version="0.1.0",
    description="Shared REST API: аккаунты, прокси, персоны (Telegram Mini App).",
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(accounts.router)
app.include_router(login.router)
app.include_router(monitoring.router)
app.include_router(proxies.router)
app.include_router(personas.router)
app.include_router(commenting_router)
