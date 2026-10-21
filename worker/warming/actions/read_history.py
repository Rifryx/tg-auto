"""«Чтение» истории канала: подтянуть сообщения и продвинуть read-статус."""

from __future__ import annotations

import random
from typing import Optional

from core.enums import WarmingActionType
from core.models import Account, Persona
from worker.warming.actions.base import DISCOVERY_CHANNELS, action, pick_target


@action(WarmingActionType.READ_HISTORY)
async def execute(
    client,
    account: Account,
    *,
    persona: Optional[Persona] = None,
    rng: Optional[random.Random] = None,
    **_: object,
):
    rng = rng or random.Random()
    target = pick_target(rng, persona, "channel", DISCOVERY_CHANNELS)
    count = rng.randint(10, 30)
    messages = await client.get_messages(target, limit=count)
    await client.send_read_acknowledge(target)
    read = len(messages) if messages is not None else count
    # meta: где (target) и сколько сообщений отмечено прочитанными.
    return target, {"read": int(read)}
