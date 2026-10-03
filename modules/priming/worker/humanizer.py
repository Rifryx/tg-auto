"""Фоновая имитация активности между праймами (spec §10, промпт 5.1).

Одна задача = один тик humanizer'а для одного campaign_account:
* off        — noop (в оркестраторе тоже не планируется);
* balanced   — прочитать 1–3 поста в канале из пула warming;
* aggressive — то же + reaction + (иногда) просмотр stories.

Инварианты:
* работает через ``worker.client_pool`` + ``around_telethon_call`` —
  health-инциденты ловятся так же, как в обычных warming-actions;
* никогда не пишет сообщения незнакомцам (только read/react/view);
* если campaign_account.state != idle — no-op (executor уже держит
  клиента; лишний параллельный доступ не даст ускорения и мешает
  advisory-lock'у).

Оркестратор (см. промпт 2.3, доп-логика в этом коммите) планирует
``priming.humanizer_beat`` в паузе между execute_prime и следующим tick'ом
того же аккаунта.
"""

from __future__ import annotations

import random
from typing import Optional

import structlog

from modules.priming.repositories import CampaignAccountRepository, CampaignRepository
from modules.priming.schemas.enums import HumanizerMode, PrimingAccountState
from worker.health import around_telethon_call
from worker.warming.actions.base import DISCOVERY_CHANNELS

get_logger = structlog.get_logger

HUMANIZER_ACTION_TYPE = "warming"  # используем те же governor-окна, что и warm-up


# --- ctx helpers ------------------------------------------------------------


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _pool(ctx: dict):
    return ctx["client_pool"]


def _publisher(ctx: dict):
    return ctx.get("publisher")


def _session_factory(ctx: dict):
    return ctx["session_factory"]


# --- сама задача ------------------------------------------------------------


async def humanizer_beat(
    ctx: dict, campaign_id: int, campaign_account_id: int,
) -> Optional[dict]:
    """Один humanizer-тик. Возвращает компактный отчёт или None.

    * ``None`` — задача пропущена (campaign paused, account non-idle,
      humanizer off, governor rejected).
    """
    log = get_logger()
    session_factory = _session_factory(ctx)
    rng = _rng(ctx)

    # 1. Читаем состояние кампании и аккаунта.
    with session_factory() as session:
        campaign = CampaignRepository(session).get_by_id(campaign_id)
        if campaign is None:
            return None
        mode = HumanizerMode(campaign.humanizer_mode)
        if mode is HumanizerMode.OFF:
            return None

        ca_repo = CampaignAccountRepository(session)
        ca = ca_repo.get_by_id(campaign_account_id)
        if ca is None:
            return None
        if ca.state != PrimingAccountState.IDLE.value:
            # Executor уже работает с этим аккаунтом — не мешаем.
            log.info(
                "priming.humanizer.skip.non_idle",
                campaign_account_id=campaign_account_id,
                state=ca.state,
            )
            return None
        account_id = ca.account_id

    # 2. Governor: используем warming-квоту — humanizer ест те же лимиты,
    # что и общий warming-цикл, чтобы не задваивать нагрузку.
    if not await ctx["governor"].check_and_reserve(
        account_id, HUMANIZER_ACTION_TYPE,
    ):
        log.info("priming.humanizer.rate_limited", account_id=account_id)
        return None

    # 3. Открываем клиента и выполняем действия.
    pool = _pool(ctx)
    client = await pool.get(account_id)
    executed: list[str] = []
    try:
        # BALANCED: 1–3 read_history в случайных каналах.
        reads = rng.randint(1, 3)
        for _ in range(reads):
            channel = _pick_channel(rng)
            await around_telethon_call(
                _make_read(client, channel, rng),
                account_id=account_id,
                session_factory=session_factory,
                publisher=_publisher(ctx),
            )
            executed.append(f"read:{channel}")

        # AGGRESSIVE: сверху — одна реакция и (иногда) просмотр stories.
        if mode is HumanizerMode.AGGRESSIVE:
            channel = _pick_channel(rng)
            try:
                await around_telethon_call(
                    _make_react(client, channel, rng),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=_publisher(ctx),
                )
                executed.append(f"react:{channel}")
            except Exception as exc:  # pragma: no cover — best-effort
                log.info("priming.humanizer.react.skipped",
                         error=type(exc).__name__)

            if rng.random() < 0.5:
                channel = _pick_channel(rng)
                try:
                    await around_telethon_call(
                        _make_view_stories(client, channel),
                        account_id=account_id,
                        session_factory=session_factory,
                        publisher=_publisher(ctx),
                    )
                    executed.append(f"stories:{channel}")
                except Exception as exc:  # pragma: no cover — best-effort
                    log.info("priming.humanizer.stories.skipped",
                             error=type(exc).__name__)
    finally:
        await pool.release(account_id)

    log.info(
        "priming.humanizer.beat.done",
        campaign_account_id=campaign_account_id,
        mode=mode.value,
        executed=executed,
    )
    return {"executed": executed, "mode": mode.value}


# --- вспомогательные --------------------------------------------------------


def _pick_channel(rng: random.Random) -> str:
    return rng.choice(list(DISCOVERY_CHANNELS)) if DISCOVERY_CHANNELS else "@durov"


def _make_read(client, channel: str, rng: random.Random):
    async def _do():
        await client.get_messages(channel, limit=rng.randint(3, 10))
        await client.send_read_acknowledge(channel)
    return _do


def _make_react(client, channel: str, rng: random.Random):
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    async def _do():
        messages = await client.get_messages(channel, limit=1)
        if not messages:
            return
        emoji = rng.choice(["👍", "🔥", "❤️", "👏"])
        await client(SendReactionRequest(
            peer=channel,
            msg_id=messages[0].id,
            reaction=[ReactionEmoji(emoticon=emoji)],
        ))
    return _do


def _make_view_stories(client, channel: str):
    from telethon.tl.functions.stories import GetPeerStoriesRequest

    async def _do():
        await client(GetPeerStoriesRequest(peer=channel))
    return _do
