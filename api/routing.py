"""Единый список роутеров API.

Его используют оба приложения — прод ``api.asgi:create_app`` и «голое»
``api.main:app`` (тесты, локальный uvicorn). Новый роутер добавляется ТОЛЬКО
здесь, иначе приложения расходятся и локально ловится 404 на рабочем эндпоинте.
"""

from __future__ import annotations

from fastapi import FastAPI


def include_all_routers(app: FastAPI) -> None:
    from api.routers import (
        accounts,
        admin,
        autopilot,
        ban_risk,
        billing,
        bulk_jobs,
        login,
        media_assets,
        monitoring,
        personas,
        profile_assets,
        projects,
        proxies,
    )
    from modules.commenting.api import router as commenting_router
    from modules.commenting.api.channels import router as channels_router

    for router in (
        accounts.router,
        login.router,
        monitoring.router,
        proxies.router,
        personas.router,
        billing.router,
        bulk_jobs.router,
        admin.router,
        ban_risk.router,
        autopilot.router,
        projects.router,
        profile_assets.router,
        media_assets.router,
        commenting_router,
        channels_router,
    ):
        app.include_router(router)
