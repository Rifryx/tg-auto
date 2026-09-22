"""«Просмотр» медиа: подтянуть последние сообщения канала с медиа."""

from __future__ import annotations

import random
from typing import Optional

from core.enums import WarmingActionType
from core.models import Account, Persona
from worker.warming.actions.base import DISCOVERY_CHANNELS, action, pick_target


@action(WarmingActionType.VIEW_MEDIA)
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
    await client.get_messages(target, limit=rng.randint(5, 15))
    return target
