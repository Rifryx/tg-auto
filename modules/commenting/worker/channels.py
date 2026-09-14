"""Разрешение и подписка на каналы аккаунта (аккаунт-центричный мониторинг).

Каждый аккаунт держит свой список каналов (:class:`MonitoredChannel`). Задачи
здесь превращают «сырой» ввод пользователя (ссылка на канал / @username / инвайт
/ ссылка на папку-addlist) в реальную подписку через Telethon и заполняют
техполя строки (``channel_tg_id``, ``discussion_group_id``, ``title``), после
чего канал переходит в статус ``working`` и слушатель начинает ловить в нём посты
(см. :mod:`modules.commenting.worker.registry`).

Тела задач:
- ``resolve_channel`` — вступить/подписаться и разрешить discussion-группу; для
  папки — развернуть в дочерние строки и поставить их в очередь на resolve;
- ``leave_channel`` — отписаться (LeaveChannel), опция ``?unsubscribe=true`` в API.

Разрешение ссылок и join — единственное место, где модуль трогает Telethon
напрямую; всё обёрнуто в :func:`around_telethon_call` (health-инциденты, flood).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from modules.commenting.repositories import MonitoredChannelRepository
from worker.client_pool import ClientPool
from worker.health import around_telethon_call

get_logger = structlog.get_logger

CHANNEL_LIFECYCLE_CHANNEL = "channel_lifecycle"
ACTION_ATTACH = "attach"
ACTION_DETACH = "detach"


# --- ctx-инъекции (как в runner) ---------------------------------------------


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


# --- разбор пользовательского ввода ------------------------------------------


def _strip_url(ref: str) -> str:
    ref = ref.strip()
    for prefix in ("https://", "http://"):
        if ref.startswith(prefix):
            ref = ref[len(prefix) :]
    if ref.startswith("t.me/"):
        ref = ref[len("t.me/") :]
    elif ref.startswith("telegram.me/"):
        ref = ref[len("telegram.me/") :]
    return ref.strip("/")


def _folder_slug(ref: str) -> Optional[str]:
    """Слаг папки-addlist (``t.me/addlist/<slug>``) или None."""
    body = _strip_url(ref)
    if body.startswith("addlist/"):
        return body[len("addlist/") :] or None
    return None


def _invite_hash(ref: str) -> Optional[str]:
    """Хэш приватного инвайта (``t.me/+xxxx`` или ``t.me/joinchat/xxxx``) или None."""
    body = _strip_url(ref)
    if body.startswith("+"):
        return body[1:] or None
    if body.startswith("joinchat/"):
        return body[len("joinchat/") :] or None
    return None


def _public_ref(ref: str) -> str:
    """Публичный @username/имя канала для get_entity."""
    body = _strip_url(ref)
    return body.lstrip("@")


# --- resolve_channel ---------------------------------------------------------


async def _join_and_resolve(
    client: Any, input_ref: str, *, account_id: int, session_factory, publisher, now
) -> dict:
    """Вступает в канал и разрешает его discussion-группу. Возвращает техполя."""
    from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest

    invite = _invite_hash(input_ref)

    async def _call(coro_factory):
        return await around_telethon_call(
            coro_factory,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )

    if invite is not None:
        updates = await _call(lambda: client(ImportChatInviteRequest(invite)))
        chats = getattr(updates, "chats", None) or []
        entity = chats[0] if chats else None
    else:
        ref = _public_ref(input_ref)
        entity = await _call(lambda: client.get_entity(ref))
        await _call(lambda: client(JoinChannelRequest(entity)))

    if entity is None:
        raise RuntimeError(f"cannot resolve entity for {input_ref!r}")

    full = await _call(lambda: client(GetFullChannelRequest(entity)))
    linked = getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
    return {
        "channel_ref": getattr(entity, "username", None) or _public_ref(input_ref),
        "channel_tg_id": getattr(entity, "id", None),
        "title": getattr(entity, "title", None),
        "discussion_group_id": linked,
    }


async def _resolve_folder(
    client: Any, slug: str, *, account_id: int, session_factory, publisher, now
) -> list[str]:
    """Вступает в папку-addlist и возвращает ref'ы каналов из неё."""
    from telethon.tl.functions.chatlists import (
        CheckChatlistInviteRequest,
        JoinChatlistInviteRequest,
    )
    from telethon.tl.types import InputChatlistDialogFilter

    async def _call(coro_factory):
        return await around_telethon_call(
            coro_factory,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )

    info = await _call(lambda: client(CheckChatlistInviteRequest(slug=slug)))
    peers = list(getattr(info, "peers", None) or getattr(info, "already_peers", []) or [])
    # Вступаем в папку целиком (Telegram сам подпишет на её каналы).
    if peers:
        await _call(
            lambda: client(
                JoinChatlistInviteRequest(slug=slug, peers=peers)
            )
        )
    refs: list[str] = []
    for peer in peers:
        try:
            entity = await _call(lambda p=peer: client.get_entity(p))
        except Exception:  # noqa: BLE001 - один битый peer не рушит всю папку
            continue
        username = getattr(entity, "username", None)
        refs.append(f"@{username}" if username else str(getattr(entity, "id", peer)))
    return refs


async def resolve_channel(ctx: dict, channel_id: int) -> str:
    """Разрешает один :class:`MonitoredChannel`: подписка + discussion-группа.

    Для папки — разворачивает в дочерние строки и ставит их на resolve. При
    ошибке помечает строку ``failed`` (пользователь видит текст в UI).
    """
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    now = _now(ctx)
    log = get_logger()

    with session_factory() as session:
        ch = MonitoredChannelRepository(session).get(channel_id)
        if ch is None:
            return "missing"
        account_id = ch.account_id
        input_ref = ch.input_ref
        is_folder = ch.is_folder

    pool = _pool(ctx)
    client = None
    try:
        # get() внутри try: битая сессия/прокси (CryptoError и т.п.) должна
        # помечать канал failed с текстом, а не оставлять его навсегда pending.
        client = await pool.get(account_id)
        if is_folder:
            slug = _folder_slug(input_ref)
            if slug is None:
                raise RuntimeError(f"not a folder link: {input_ref!r}")
            child_refs = await _resolve_folder(
                client, slug, account_id=account_id,
                session_factory=session_factory, publisher=publisher, now=now,
            )
            children: list[int] = []
            with session_factory() as session:
                repo = MonitoredChannelRepository(session)
                for ref in child_refs:
                    if repo.get_by_account_input(account_id, ref) is not None:
                        continue
                    children.append(repo.create(account_id, ref, is_folder=False).id)
                # Папка-строка выполнила роль контейнера — помечаем working.
                repo.mark_working(
                    channel_id, channel_ref=slug, channel_tg_id=None,
                    title=f"Папка: {len(child_refs)} каналов",
                    discussion_group_id=None, subscribed=True,
                )
                session.commit()
            task_queue = _task_queue(ctx)
            for child_id in children:
                await task_queue.enqueue(
                    TaskName.COMMENTING_RESOLVE_CHANNEL, child_id
                )
            log.info(
                "commenting.resolve_channel.folder",
                channel_id=channel_id, children=len(children),
            )
            return "folder"

        info = await _join_and_resolve(
            client, input_ref, account_id=account_id,
            session_factory=session_factory, publisher=publisher, now=now,
        )
        with session_factory() as session:
            MonitoredChannelRepository(session).mark_working(channel_id, **info)
            session.commit()
        publish_channel_lifecycle(publisher, account_id, channel_id, ACTION_ATTACH)
        log.info(
            "commenting.resolve_channel.working",
            channel_id=channel_id, account_id=account_id,
            discussion_group_id=info.get("discussion_group_id"),
        )
        return "working"
    except Exception as exc:  # noqa: BLE001 - ошибку показываем пользователю в UI
        with session_factory() as session:
            MonitoredChannelRepository(session).mark_failed(channel_id, repr(exc))
            session.commit()
        log.warning(
            "commenting.resolve_channel.failed",
            channel_id=channel_id, error=repr(exc),
        )
        return "failed"
    finally:
        if client is not None:
            await pool.release(account_id)


# --- leave_channel -----------------------------------------------------------


async def leave_channel(
    ctx: dict, account_id: int, channel_ref: str, channel_tg_id: Optional[int] = None
) -> bool:
    """Отписывает аккаунт от канала (LeaveChannel). Ошибки не критичны."""
    from telethon.tl.functions.channels import LeaveChannelRequest

    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    now = _now(ctx)
    pool = _pool(ctx)
    client = None
    try:
        client = await pool.get(account_id)
        target: Any = channel_tg_id if channel_tg_id is not None else _public_ref(channel_ref)
        entity = await around_telethon_call(
            lambda: client.get_entity(target),
            account_id=account_id, session_factory=session_factory,
            publisher=publisher, now=now,
        )
        await around_telethon_call(
            lambda: client(LeaveChannelRequest(entity)),
            account_id=account_id, session_factory=session_factory,
            publisher=publisher, now=now,
        )
        get_logger().info(
            "commenting.leave_channel.done", account_id=account_id, channel=channel_ref
        )
        return True
    except Exception as exc:  # noqa: BLE001 - отписка best-effort
        get_logger().warning(
            "commenting.leave_channel.failed",
            account_id=account_id, channel=channel_ref, error=repr(exc),
        )
        return False
    finally:
        if client is not None:
            await pool.release(account_id)


# --- pub/sub жизненного цикла канала -----------------------------------------


def publish_channel_lifecycle(
    publisher: Any, account_id: int, channel_id: int, action: str
) -> None:
    """Публикует ``{account_id, channel_id, action}`` в ``channel_lifecycle``.

    Реестр слушателей (:mod:`registry`) реагирует attach/detach БЕЗ рестарта.
    no-op, если publisher=None (тесты/DEV без Redis).
    """
    if publisher is None:
        return
    publisher.publish(
        CHANNEL_LIFECYCLE_CHANNEL,
        {"account_id": account_id, "channel_id": channel_id, "action": action},
    )
