"""Редкая реакция на свежий пост канала."""

from __future__ import annotations

import random

from core.enums import WarmingActionType
from core.models import Account
from worker.warming.actions.base import DISCOVERY_CHANNELS, action


@action(WarmingActionType.REACTION)
async def execute(client, account: Account):
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    target = random.choice(DISCOVERY_CHANNELS)
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
