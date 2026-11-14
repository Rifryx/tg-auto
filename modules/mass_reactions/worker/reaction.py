"""Постановка одной реакции через Telethon (spec §1, переиспользуем shilling).

Тонкая обёртка над ``SendReactionRequest`` + ``ReactionEmoji``. Реальный вызов
оборачивается governor'ом на уровне задачи ``place_reaction`` (следующий шаг);
здесь — изолированная функция отправки, чтобы её можно было переиспользовать и
подменять в тестах.
"""

from __future__ import annotations

from typing import Any


async def send_reaction(client: Any, *, chat_id: int, msg_id: int, emoji: str) -> int:
    """Ставит ``emoji`` на сообщение ``msg_id`` в чате ``chat_id``.

    Возвращает ``msg_id`` при успехе; исключения Telethon пробрасываются наверх
    и классифицируются через :func:`modules.mass_reactions.worker.errors.
    classify_reaction_error`.
    """
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    await client(
        SendReactionRequest(
            peer=chat_id, msg_id=msg_id, reaction=[ReactionEmoji(emoticon=emoji)]
        )
    )
    return msg_id
