"""Редкая реакция на свежий пост канала."""

from __future__ import annotations

import random
from typing import Optional

from core.enums import WarmingActionType
from core.models import Account, Persona
from worker.warming.actions.base import DISCOVERY_CHANNELS, action, pick_target


@action(WarmingActionType.REACTION)
async def execute(
    client,
    account: Account,
    *,
    persona: Optional[Persona] = None,
    rng: Optional[random.Random] = None,
    **_: object,
):
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    rng = rng or random.Random()
    target = pick_target(rng, persona, "channel", DISCOVERY_CHANNELS)
    messages = await client.get_messages(target, limit=1)
    if not messages:
        raise RuntimeError(f"no messages to react to in {target!r}")
    # Разнообразим реакцию — не всегда «палец вверх», так естественнее.
    emoji = rng.choice(["👍", "🔥", "❤️", "👏", "😁", "🤯", "🎉"])
    msg_id = messages[0].id
    await client(
        SendReactionRequest(
            peer=target,
            msg_id=msg_id,
            reaction=[ReactionEmoji(emoticon=emoji)],
        )
    )
    # meta: где (target), на какое сообщение (message_id) и какая реакция (emoji).
    return target, {"emoji": emoji, "message_id": int(msg_id)}
