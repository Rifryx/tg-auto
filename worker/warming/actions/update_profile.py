"""Редкая правка профиля (например, поле «о себе»)."""

from __future__ import annotations

from core.enums import WarmingActionType
from core.models import Account
from worker.warming.actions.base import action


@action(WarmingActionType.UPDATE_PROFILE)
async def execute(client, account: Account, **_: object):
    from telethon.tl.functions.account import UpdateProfileRequest

    about = account.bio or "Hi there!"
    await client(UpdateProfileRequest(about=about[:70]))
    return None
