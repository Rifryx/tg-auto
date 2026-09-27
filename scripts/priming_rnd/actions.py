"""R&D-обёртки над кандидатами MTProto-триггеров прайминга.

Каждая функция:
- принимает подключённый ``TelegramClient`` и целевой peer;
- дёргает **один** MTProto-метод (кандидат из ``docs/priming-spec.md`` §5);
- возвращает :class:`ActionResult` с записанной сигнатурой вызова и данными
  ответа (либо пойманной ``RPCError``).

Никакой ретрай-логики / rate-limit governor'а тут нет — они живут снаружи
(см. :mod:`scripts.priming_rnd.runner`). Задача этих функций — минимальная
воспроизводимая проба одного триггера, чтобы оператор мог сравнить push,
артефакт в чате и текст ошибки на живых аккаунтах.

Скрипт **никогда** не должен вызываться в продакшн-пайплайне; это чистая R&D.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.tl.functions.contacts import AddContactRequest, DeleteContactsRequest
from telethon.tl.functions.messages import (
    RequestEncryptionRequest,
    SetHistoryTTLRequest,
)


TriggerAction = str  # локальный alias; настоящий enum появится на промпте 1.2


@dataclass
class ActionResult:
    """Результат одной пробы: что дёрнули, что вернулось, сколько мс заняло."""

    action: TriggerAction
    mtproto: str
    args: dict[str, Any]
    ok: bool
    latency_ms: int
    response_repr: str | None = None
    rpc_error: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def _call(
    action: TriggerAction, mtproto: str, args: dict[str, Any], coro
) -> ActionResult:
    started = time.monotonic()
    try:
        response = await coro
    except RPCError as exc:
        return ActionResult(
            action=action,
            mtproto=mtproto,
            args=args,
            ok=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            rpc_error=f"{type(exc).__name__}: {exc}",
        )
    return ActionResult(
        action=action,
        mtproto=mtproto,
        args=args,
        ok=True,
        latency_ms=int((time.monotonic() - started) * 1000),
        response_repr=repr(response)[:400],
    )


# ---------------------------------------------------------------------------
# Кандидаты триггеров. Каждая функция — один action из §5 спеки.
# ---------------------------------------------------------------------------


async def set_ttl_1d(client: TelegramClient, peer) -> ActionResult:
    """«X включил автоудаление сообщений» (24 ч)."""
    return await _call(
        action="set_ttl_1d",
        mtproto="messages.setHistoryTTL",
        args={"peer": str(peer), "period": 86_400},
        coro=client(SetHistoryTTLRequest(peer=peer, period=86_400)),
    )


async def set_ttl_off(client: TelegramClient, peer) -> ActionResult:
    """«X выключил автоудаление сообщений» (обратный триггер)."""
    return await _call(
        action="set_ttl_off",
        mtproto="messages.setHistoryTTL",
        args={"peer": str(peer), "period": 0},
        coro=client(SetHistoryTTLRequest(peer=peer, period=0)),
    )


async def secret_chat_request(client: TelegramClient, peer) -> ActionResult:
    """«X отправил приглашение в секретный чат» — самый чистый кандидат."""
    input_user = await client.get_input_entity(peer)
    # random_id / g_a — генерируются Telethon по умолчанию через хелпер.
    # Для R&D вручную заполняем поля минимально: 256-битное g_a рандом.
    import os

    random_id = int.from_bytes(os.urandom(8), "little", signed=True)
    g_a = os.urandom(256)
    return await _call(
        action="secret_chat_request",
        mtproto="messages.requestEncryption",
        args={"user_id": str(input_user), "random_id": random_id},
        coro=client(
            RequestEncryptionRequest(
                user_id=input_user,
                random_id=random_id,
                g_a=g_a,
            )
        ),
    )


async def contact_added(client: TelegramClient, peer) -> ActionResult:
    """«X добавил вас в контакты» — работает при известной phone/username."""
    input_user = await client.get_input_entity(peer)
    return await _call(
        action="contact_added",
        mtproto="contacts.addContact",
        args={"user_id": str(input_user), "add_phone_privacy_exception": True},
        coro=client(
            AddContactRequest(
                id=input_user,
                first_name="R",
                last_name="D",
                phone="",
                add_phone_privacy_exception=True,
            )
        ),
    )


async def contact_removed(client: TelegramClient, peer) -> ActionResult:
    """Откат ``contact_added`` — чтобы прогон не оставлял мусорных контактов."""
    input_user = await client.get_input_entity(peer)
    return await _call(
        action="contact_removed",
        mtproto="contacts.deleteContacts",
        args={"user_id": str(input_user)},
        coro=client(DeleteContactsRequest(id=[input_user])),
    )


# Публичный реестр — по нему CLI и матрица в docs понимают, какие пробы есть.
REGISTRY: dict[TriggerAction, Any] = {
    "set_ttl_1d": set_ttl_1d,
    "set_ttl_off": set_ttl_off,
    "secret_chat_request": secret_chat_request,
    "contact_added": contact_added,
    "contact_removed": contact_removed,
}
