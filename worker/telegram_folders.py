"""Разворачивание Telegram addlist-папок (worker-scope, этап 8, backlog #2).

``CheckChatlistInvite`` + ``JoinChatlistInvite`` — низкоуровневый Telethon
эквивалент того, что в UI смотрится как «добавить папку». Кладём helper сюда,
чтобы им пользовались:
* :mod:`modules.commenting.worker.channels` (аккаунт-центричный мониторинг);
* :mod:`modules.bulk.actions.join_channels` (bulk join+folders).

Helper НЕ пишет в БД (в отличие от commenting.channels) — только join и сбор
списка peer'ов; вызывающий сам решает, что делать с результатом.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.queue.publisher import Publisher
from worker.health.monitor import around_telethon_call


@dataclass
class FolderJoinResult:
    """Результат разворачивания addlist:

    * ``joined_refs`` — публичные ссылки (``@username``) или строковые id
      каналов, в которые аккаунт реально вступил.
    * ``already_in`` — сколько каналов из папки уже были в списке аккаунта
      (Telegram кладёт их в ``already_peers``, повторно не вступаем).
    """

    joined_refs: list[str]
    already_in: int


async def join_folder(
    client: Any,
    slug: str,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Optional[Publisher] = None,
) -> FolderJoinResult:
    """Развернуть addlist-папку в набор каналов и вступить.

    Возвращает :class:`FolderJoinResult`. Ошибки самой папки (истекший slug,
    невалидный) уходят наверх — вызывающий фиксирует их как per-ref error.
    """
    from telethon.tl.functions.chatlists import (
        CheckChatlistInviteRequest,
        JoinChatlistInviteRequest,
    )

    async def _call(coro_factory):
        return await around_telethon_call(
            coro_factory,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )

    info = await _call(lambda: client(CheckChatlistInviteRequest(slug=slug)))
    new_peers = list(getattr(info, "peers", None) or [])
    already = list(getattr(info, "already_peers", None) or [])

    if new_peers:
        await _call(
            lambda: client(JoinChatlistInviteRequest(slug=slug, peers=new_peers))
        )

    joined: list[str] = []
    for peer in new_peers:
        try:
            entity = await _call(lambda p=peer: client.get_entity(p))
        except Exception:  # noqa: BLE001 - один битый peer не рушит всю папку
            continue
        username = getattr(entity, "username", None)
        joined.append(
            f"@{username}" if username else str(getattr(entity, "id", peer))
        )
    return FolderJoinResult(joined_refs=joined, already_in=len(already))
