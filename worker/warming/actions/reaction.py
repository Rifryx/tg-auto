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

    target = pick_target(rng or random.Random(), persona, "channel", DISCOVERY_CHANNELS)
    messages = await client.get_messages(target, limit=1)
    if not messages:
        raise RuntimeError(f"no messages to react to in {target!r}")
    await client(
        SendReactionRequest(
            peer=target,
            msg_id=messages[0].id,
            reaction=[ReactionEmoji(emoticon="👍")],
        )
    )
    return target
