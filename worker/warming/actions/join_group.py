"""Вступление в публичную группу (действие прогрева)."""

from __future__ import annotations

import random
from typing import Optional

from core.enums import WarmingActionType
from core.models import Account, Persona
from worker.warming.actions.base import DISCOVERY_GROUPS, action, pick_target


@action(WarmingActionType.JOIN_GROUP)
async def execute(
    client,
    account: Account,
    *,
    persona: Optional[Persona] = None,
    rng: Optional[random.Random] = None,
    **_: object,
):
    from telethon.tl.functions.channels import JoinChannelRequest

    target = pick_target(rng or random.Random(), persona, "group", DISCOVERY_GROUPS)
    await client(JoinChannelRequest(target))
    return target
