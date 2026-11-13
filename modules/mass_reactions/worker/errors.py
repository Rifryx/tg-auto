"""Классификация ошибок Telethon при постановке реакции → ``ReactionOutcome``.

Определяем по имени класса исключения, чтобы не зависеть от набора классов в
конкретной версии Telethon и чтобы логика была юнит-тестируемой с фейковыми
исключениями.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from modules.mass_reactions.schemas.enums import ReactionOutcome


@dataclass(frozen=True)
class ReactionError:
    outcome: ReactionOutcome
    error_code: str
    flood_wait_sec: Optional[int] = None


# Имя класса исключения Telethon → (outcome, требуется ли flood_wait_sec).
_FORBIDDEN = {
    "ChatWriteForbiddenError",
    "ForbiddenError",
    "ChatAdminRequiredError",
    "ReactionInvalidError",
    "UserBannedInChannelError",
    "ChannelPrivateError",
}
_NOT_FOUND = {
    "MessageIdInvalidError",
    "MessageDeleteForbiddenError",
    "MsgIdInvalidError",
}


def classify_reaction_error(exc: BaseException) -> ReactionError:
    name = type(exc).__name__
    code = name
    if name == "FloodWaitError":
        seconds = getattr(exc, "seconds", None)
        return ReactionError(ReactionOutcome.FLOOD_WAIT, code, seconds)
    if name == "PeerFloodError":
        return ReactionError(ReactionOutcome.PEER_FLOOD, code)
    if name in _FORBIDDEN:
        return ReactionError(ReactionOutcome.FORBIDDEN, code)
    if name in _NOT_FOUND:
        return ReactionError(ReactionOutcome.NOT_FOUND, code)
    return ReactionError(ReactionOutcome.INTERNAL_ERROR, code)
