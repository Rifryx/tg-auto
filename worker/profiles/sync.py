"""Синхронизация реального Telegram-профиля аккаунта в нашу БД.

После логина (и по кнопке «обновить») тянем из Telegram настоящие имя/фамилию,
@username, bio и аватар, а также статус 2FA — и сохраняем. Иначе аккаунт в UI
выглядит пустым, а карточка 2FA показывает «не установлен», хотя пароль есть.

Профильные поля пишем в ``accounts`` (``AccountUpdate``), флаги (has_2fa и пр.) —
в ``account_health``. Аватар сохраняем как base64 data-URL (фронт так и рисует
``<img src=avatar_url>``), без отдельного файлового хранилища.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from telethon.tl.functions.account import GetPasswordRequest

from core.repositories.account import AccountRepository
from core.repositories.account_health import AccountHealthRepository
from core.schemas.account import AccountUpdate
from core.schemas.account_health import AccountHealthUpdate
from worker.client_pool import ClientPool

# Плоский логгер (не worker.tasks.logging) — иначе цикл импорта: handlers → sync
# → worker.tasks.logging → worker.tasks(__init__) → handlers.
logger = logging.getLogger("worker.sync_profile")

PROFILE_UPDATED_CHANNEL = "account_profile_updated"


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


async def sync_profile_impl(ctx: dict, account_id: int) -> dict[str, Any]:
    """Подтянуть профиль + статус 2FA из Telegram и сохранить."""
    pool = _pool(ctx)
    publisher = ctx.get("publisher")
    session_factory = ctx["session_factory"]

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    has_avatar = False
    has_2fa: Optional[bool] = None

    client = await pool.get(account_id)
    try:
        await client.connect()
        me = await client.get_me()
        first_name = getattr(me, "first_name", None)
        last_name = getattr(me, "last_name", None)
        username = getattr(me, "username", None)
        has_avatar = getattr(me, "photo", None) is not None

        # bio — из full-user (get_entity('me').about).
        try:
            entity = await client.get_entity("me")
            about = getattr(entity, "about", None)
            bio = about if about else None
        except Exception as exc:  # noqa: BLE001
            logger.info("sync_profile.bio_skip acc=%s err=%r", account_id, exc)

        # Аватар → base64 data-URL (только если есть и скачался).
        if has_avatar:
            try:
                data = await client.download_profile_photo("me", file=bytes)
                if data:
                    avatar_url = (
                        "data:image/jpeg;base64," + base64.b64encode(data).decode()
                    )
            except Exception as exc:  # noqa: BLE001
                logger.info("sync_profile.avatar_skip acc=%s err=%r", account_id, exc)

        # 2FA — наличие облачного пароля (без ввода).
        try:
            pwd = await client(GetPasswordRequest())
            has_2fa = bool(getattr(pwd, "has_password", False))
        except Exception as exc:  # noqa: BLE001
            logger.info("sync_profile.2fa_skip acc=%s err=%r", account_id, exc)
    finally:
        await pool.release(account_id)

    with session_factory() as session:
        profile_kwargs: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "bio": bio,
        }
        # avatar_url выставляем только если реально получили — чтобы не затирать
        # вручную поставленный аватар при неудачной загрузке.
        if avatar_url is not None:
            profile_kwargs["avatar_url"] = avatar_url
        AccountRepository(session).update(account_id, AccountUpdate(**profile_kwargs))
        AccountHealthRepository(session).update(
            account_id,
            AccountHealthUpdate(
                has_2fa=has_2fa,
                has_username=bool(username),
                has_avatar=has_avatar,
                has_bio=bool(bio and bio.strip()),
            ),
        )
        session.commit()

    if publisher is not None:
        publisher.publish(PROFILE_UPDATED_CHANNEL, {"account_id": account_id})
    logger.info(
        "sync_profile.done acc=%s has_username=%s has_avatar=%s has_2fa=%s",
        account_id, bool(username), has_avatar, has_2fa,
    )
    return {"account_id": account_id, "has_2fa": has_2fa, "username": username}
