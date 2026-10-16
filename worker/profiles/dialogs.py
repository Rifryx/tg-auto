"""Диалоги аккаунта: снапшот всех каналов/групп + выход из них.

Снапшот кладём в Redis (живой, кэш-подобный список — не нужна таблица/миграция),
ключ ``account:{id}:dialogs``. API читает его тем же клиентом Redis.

* ``account.sync_dialogs`` — тянет ``get_dialogs()``, оставляет каналы/группы
  (приватные чаты с людьми не трогаем), пишет снапшот.
* ``account.leave_dialogs`` — выходит из указанных (или всех) диалогов, затем
  обновляет снапшот.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import redis
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.messages import DeleteChatUserRequest
from telethon.tl.types import InputChannel, InputUserSelf

from core.config import get_settings
from worker.client_pool import ClientPool

logger = logging.getLogger("worker.dialogs")

DIALOGS_TTL_SECONDS = 3600  # снапшот живёт час, обновляется по кнопке


def dialogs_key(account_id: int) -> str:
    return f"account:{account_id}:dialogs"


def _redis() -> "redis.Redis":
    return redis.Redis.from_url(get_settings().redis_url)


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _dialog_kind(dialog: Any, entity: Any) -> Optional[str]:
    """channel | group — или None для приватных чатов с людьми (их не берём)."""
    if getattr(entity, "broadcast", False):
        return "channel"
    if getattr(entity, "megagroup", False):
        return "group"
    if getattr(dialog, "is_group", False):  # базовый чат (Chat)
        return "group"
    return None


async def sync_dialogs_impl(ctx: dict, account_id: int) -> dict[str, Any]:
    """Снять снапшот каналов/групп аккаунта в Redis."""
    pool = _pool(ctx)
    items: list[dict[str, Any]] = []
    client = await pool.get(account_id)
    try:
        await client.connect()
        for dialog in await client.get_dialogs():
            entity = dialog.entity
            kind = _dialog_kind(dialog, entity)
            if kind is None:
                continue
            items.append(
                {
                    "id": int(getattr(entity, "id", 0)),
                    "access_hash": getattr(entity, "access_hash", None),
                    "kind": kind,
                    "title": dialog.name or getattr(entity, "title", None) or "",
                    "username": getattr(entity, "username", None),
                    "members": getattr(entity, "participants_count", None),
                    "is_creator": bool(getattr(entity, "creator", False)),
                }
            )
    finally:
        await pool.release(account_id)

    payload = {"items": items, "synced_at": datetime.now(timezone.utc).isoformat()}
    try:
        _redis().setex(dialogs_key(account_id), DIALOGS_TTL_SECONDS, json.dumps(payload))
    except Exception as exc:  # noqa: BLE001
        logger.warning("sync_dialogs.redis_fail acc=%s err=%r", account_id, exc)

    publisher = ctx.get("publisher")
    if publisher is not None:
        publisher.publish("account_dialogs_updated", {"account_id": account_id, "count": len(items)})
    logger.info("sync_dialogs.done acc=%s count=%s", account_id, len(items))
    return {"count": len(items)}


async def leave_dialogs_impl(
    ctx: dict, account_id: int, dialog_ids: Optional[list[int]] = None
) -> dict[str, Any]:
    """Выйти из указанных диалогов (или всех, если ids=None), затем обновить снапшот."""
    try:
        raw = _redis().get(dialogs_key(account_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("leave_dialogs.redis_fail acc=%s err=%r", account_id, exc)
        raw = None
    snapshot = json.loads(raw)["items"] if raw else []
    if dialog_ids is None:
        targets = snapshot
    else:
        wanted = set(int(i) for i in dialog_ids)
        targets = [d for d in snapshot if int(d["id"]) in wanted]

    pool = _pool(ctx)
    left = 0
    client = await pool.get(account_id)
    try:
        await client.connect()
        for d in targets:
            try:
                if d.get("access_hash") is not None:
                    await client(
                        LeaveChannelRequest(InputChannel(int(d["id"]), int(d["access_hash"])))
                    )
                else:  # базовый чат без access_hash
                    await client(
                        DeleteChatUserRequest(chat_id=int(d["id"]), user_id=InputUserSelf())
                    )
                left += 1
            except Exception as exc:  # noqa: BLE001 — не валим весь батч
                logger.info("leave_dialogs.skip acc=%s id=%s err=%r", account_id, d.get("id"), exc)
    finally:
        await pool.release(account_id)

    # Обновляем снапшот, чтобы UI сразу увидел актуальный список.
    await sync_dialogs_impl(ctx, account_id)
    logger.info("leave_dialogs.done acc=%s left=%s of=%s", account_id, left, len(targets))
    return {"left": left, "requested": len(targets)}
