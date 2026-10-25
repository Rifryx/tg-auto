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

    from worker.captcha import solve_captcha_in_chat

    target = pick_target(rng or random.Random(), persona, "group", DISCOVERY_GROUPS)
    await client(JoinChannelRequest(target))
    # Многие группы после join требуют пройти капчу от бота-проверки.
    # Если не пройти — аккаунт тихо кикает через N минут; ответ одной кнопкой/
    # математикой закрывает ~80% случаев. 60с хватает: капча обычно прилетает
    # за 1–3 секунды. Любой провал тихий — warming продолжит жить.
    try:
        await solve_captcha_in_chat(client, target, timeout_sec=60.0)
    except Exception:  # noqa: BLE001 — вспомогательное действие
        pass
    return target
