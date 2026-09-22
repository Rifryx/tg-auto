"""Trust-graph warming action: «естественное» взаимодействие с peer'ом
(этап 10, backlog #2).

Находим случайного peer'а того же владельца (по project_id / persona_id /
общей commenting-кампании) с публичным username, и:
* читаем последние 5–15 сообщений его переписки/аккаунта (лёгкое
  «присутствие») — эквивалент листания чата;
* с вероятностью 1/3 ставим реакцию 👀 на последнее сообщение — «увидел» —
  но НЕ на каждом tick, чтобы не спамить и не выпадать из paттерна.

Если peer'а не нашлось — возвращаем None: обёртка ``@action`` запишет DONE
с ``target=None`` (полезно для наблюдаемости, но не считается провалом).
"""

from __future__ import annotations

import random
from typing import Any, Optional

from core.enums import WarmingActionType
from core.models import Account, Persona
from worker.warming.actions.base import action
from worker.warming.trust_graph import (
    collect_campaign_ids,
    find_trust_peer_username,
)


@action(WarmingActionType.INTERACT_WITH_PEER)
async def execute(
    client,
    account: Account,
    *,
    persona: Optional[Persona] = None,
    rng: Optional[random.Random] = None,
    session_factory: Optional[Any] = None,
    **_: object,
):
    if session_factory is None:
        # Без session_factory поиск peer'а невозможен — тихо skip.
        return None
    rng = rng or random.Random()

    with session_factory() as session:
        campaign_ids = collect_campaign_ids(session, account.id)
        peer_username = find_trust_peer_username(
            session,
            account.id,
            project_id=account.project_id,
            persona_id=account.persona_id,
            campaign_ids=campaign_ids or None,
            rng=rng,
        )

    if not peer_username:
        return None

    # «Присутствие»: пролистать пару последних сообщений.
    await client.get_messages(peer_username, limit=rng.randint(5, 15))

    # 1/3 tick'ов — реакция 👀 на последнее сообщение.
    if rng.random() < 0.33:
        from telethon.tl.functions.messages import SendReactionRequest
        from telethon.tl.types import ReactionEmoji

        messages = await client.get_messages(peer_username, limit=1)
        if messages:
            await client(
                SendReactionRequest(
                    peer=peer_username,
                    msg_id=messages[0].id,
                    reaction=[ReactionEmoji(emoticon="👀")],
                )
            )
    return peer_username
