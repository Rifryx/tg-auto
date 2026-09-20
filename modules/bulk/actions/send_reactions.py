"""Bulk-action send_reactions (этап 8, backlog #3).

Массовая расстановка одной или нескольких реакций на набор постов. Payload:

* ``post_urls`` — список ссылок вида ``https://t.me/<channel>/<msg_id>``
  (публичные) или ``https://t.me/c/<channel_id>/<msg_id>`` (приватные).
* ``emojis`` — какие реакции ставить (случайно из списка на каждый пост).
* ``as_big`` — «большая» реакция с анимацией (по умолчанию False).

Каждый item — один аккаунт: он проходит по всем URL-ам, ставит реакцию.
Rate-limit governor обязателен (см. governor_key='bulk_reaction'): реакции
быстро палятся антифродом при спаме.
"""

from __future__ import annotations

import random
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health import around_telethon_call
from worker.telegram_refs import public_ref, strip_url


class SendReactionsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_urls: list[str] = Field(min_length=1, max_length=100)
    emojis: list[str] = Field(min_length=1, max_length=10)
    as_big: bool = False

    @field_validator("post_urls")
    @classmethod
    def _v_urls(cls, v: list[str]) -> list[str]:
        for u in v:
            body = strip_url(u)
            parts = body.split("/")
            if len(parts) < 2:
                raise ValueError(f"bad post url: {u!r}")
            # Последний сегмент — msg_id (число).
            try:
                int(parts[-1])
            except ValueError:
                raise ValueError(f"bad msg_id in {u!r}")
        return v


def _parse_post_url(url: str) -> tuple[str | int, int]:
    """Возвращает (channel_ref, msg_id). channel_ref: username или int-id."""
    body = strip_url(url)
    parts = body.split("/")
    msg_id = int(parts[-1])
    channel_part = parts[-2]
    # Для приватных ссылок формат: c/<channel_id>/<msg_id> → channel_part=id.
    if len(parts) >= 3 and parts[-3] == "c":
        return int(channel_part), msg_id
    return public_ref(channel_part), msg_id


async def _run(
    *,
    account_id: int,
    payload: SendReactionsPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    rng = random.Random()
    posted: list[dict] = []
    failed: list[dict] = []

    for url in payload.post_urls:
        try:
            channel_ref, msg_id = _parse_post_url(url)
        except ValueError as exc:
            failed.append({"url": url, "error": f"parse: {exc}"})
            continue
        try:
            entity = await around_telethon_call(
                lambda r=channel_ref: client.get_entity(r),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            emoji = rng.choice(payload.emojis)
            await around_telethon_call(
                lambda e=entity, m=msg_id, x=emoji: client(
                    SendReactionRequest(
                        peer=e,
                        msg_id=m,
                        reaction=[ReactionEmoji(emoticon=x)],
                        big=payload.as_big,
                    )
                ),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            posted.append({"url": url, "emoji": emoji})
        except Exception as exc:  # noqa: BLE001
            failed.append({"url": url, "error": repr(exc)})

    if not posted and failed:
        return BulkActionResult(
            ok=False, detail={"posted": posted, "failed": failed}
        )
    return BulkActionResult(ok=True, detail={"posted": posted, "failed": failed})


register(
    BulkAction(
        name=BulkActionType.SEND_REACTIONS.value,
        requires_client=True,
        payload_schema=SendReactionsPayload,
        run=_run,
        title="Поставить реакции",
        description=(
            "Каждый аккаунт ставит одну случайную реакцию из списка на каждый "
            "переданный пост. Rate-limit обязателен: реакции палятся антифродом."
        ),
        governor_key="bulk_reaction",
    )
)
