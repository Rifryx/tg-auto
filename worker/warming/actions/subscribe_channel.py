"""Подписка на публичный канал (действие прогрева)."""

from __future__ import annotations

import random
from typing import Optional

from core.enums import WarmingActionType
from core.models import Account, Persona
from worker.warming.actions.base import DISCOVERY_CHANNELS, action, pick_target


@action(WarmingActionType.SUBSCRIBE_CHANNEL)
async def execute(
    client,
    account: Account,
    *,
    persona: Optional[Persona] = None,
    rng: Optional[random.Random] = None,
    **_: object,
):
    from telethon.tl.functions.channels import JoinChannelRequest

    target = pick_target(rng or random.Random(), persona, "channel", DISCOVERY_CHANNELS)
    await client(JoinChannelRequest(target))
    return target
