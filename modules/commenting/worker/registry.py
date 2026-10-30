"""Реестр слушателей кампаний + динамика через Redis pub/sub (§5, §8.3; аудит #4/#12).

:class:`ListenerRegistry` держит по одному NewMessage-слушателю на кампанию и
умеет подключать/отключать их поштучно (``attach``/``detach``), а не «все сразу
при старте». ``load_all`` вызывается из ``worker/main.py::startup`` уже ПОСЛЕ
того, как в ``ctx['client_pool']`` положен готовый :class:`ClientPool`.

:class:`CampaignLifecycleListener` — фоновая подписка на канал
``campaign_lifecycle`` (payload ``{campaign_id, action: attach|detach}``): API
публикует туда события при смене ``campaigns.enabled`` / удалении кампании /
привязке первого аккаунта, а воркер реагирует БЕЗ рестарта. Слушатель живёт весь
процесс воркера (создаётся ``asyncio.create_task`` при старте, гасится в
shutdown).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Optional

import redis.asyncio as aioredis

from core.queue import TaskQueue
from core.repositories.account import AccountRepository
from modules.commenting.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    MonitoredChannelRepository,
)
from modules.commenting.worker.listener import (
    make_channel_post_handler,
    make_new_post_handler,
    round_robin_account,
)
from worker.tasks.logging import get_logger

CAMPAIGN_LIFECYCLE_CHANNEL = "campaign_lifecycle"
CHANNEL_LIFECYCLE_CHANNEL = "channel_lifecycle"
ACTION_ATTACH = "attach"
ACTION_DETACH = "detach"


@dataclass
class _Attached:
    """Всё, что нужно, чтобы позже корректно снять слушатель кампании."""

    client: Any
    handler: Any
    event: Any
    pool: Any
    account_id: int


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


def _timeline_redis(ctx: dict) -> Any:
    """Синхронный redis-клиент для live-таймлайна (timeline.push_event).

    НЕ использовать ctx['redis'] — это АСИНХРОННЫЙ arq-клиент, а push_event
    синхронный (pipeline().execute()); с async-клиентом события молча не
    пишутся (симптом «Таймлайн пуст»). Воркер кладёт синхронный клиент в
    ctx['redis_sync'] (worker/main.py). В тестах ключа нет → None → push_event
    просто no-op, что и нужно."""
    return ctx.get("redis_sync")


async def _resolve_discussion_entity(
    client: Any,
    _call: Any,
    *,
    channel_tg_id: Optional[int],
    discussion_group_id: int,
) -> Any:
    """Entity группы обсуждений с валидным access_hash.

    Клиент работает на ``StringSession`` (in-memory): на старте воркера
    entity-кэш ПУСТ, поэтому resolve по «сырому» id падает ``ValueError`` —
    access_hash группы неизвестен. Это и есть причина «Не удалось вступить…
    (ValueError)» и того, что ``NewMessage(chats=discussion_group_id)`` ни с чем
    не совпадает. Лечим прогревом кэша:

    1. ``get_dialogs`` кладёт в кэш каналы, на которые аккаунт подписан;
    2. ``GetFullChannel(channel)`` отдаёт связанную группу в ``full.chats``
       уже С access_hash — берём её оттуда;
    3. фолбэк — прямой ``get_entity(discussion_group_id)``.
    """
    from telethon.tl.functions.channels import GetFullChannelRequest

    if not getattr(client, "_nc_dialogs_warmed", False):
        try:
            await _call(lambda: client.get_dialogs(limit=None))
        except Exception as exc:  # noqa: BLE001 — прогрев best-effort
            get_logger().info(
                "commenting.channel_listener.warm_dialogs_failed", error=repr(exc)
            )
        setattr(client, "_nc_dialogs_warmed", True)

    if channel_tg_id is not None:
        try:
            channel_entity = await client.get_entity(channel_tg_id)
            full = await _call(lambda: client(GetFullChannelRequest(channel_entity)))
            linked_id = (
                getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
                or discussion_group_id
            )
            for chat in getattr(full, "chats", None) or []:
                if getattr(chat, "id", None) == linked_id:
                    return chat
        except Exception as exc:  # noqa: BLE001 — попробуем прямой resolve ниже
            get_logger().info(
                "commenting.channel_listener.resolve_via_channel_failed",
                error=repr(exc),
            )

    return await client.get_entity(discussion_group_id)


async def _ensure_joined_discussion(
    ctx: dict,
    client: Any,
    *,
    account_id: int,
    channel_tg_id: Optional[int],
    discussion_group_id: int,
    channel_ref: Optional[str],
    source_campaign_id: Optional[int],
    redis: Any,
) -> None:
    """Best-effort: вступить аккаунтом в discussion-группу канала.

    КЛЮЧЕВОЕ для живого мониторинга: Telethon доставляет
    ``NewMessage(chats=discussion_group_id)`` только если аккаунт — УЧАСТНИК
    этой группы. ``resolve_channel`` подписывает лишь на сам канал (broadcast),
    в группу обсуждений не вступает. Без членства handler никогда не срабатывает:
    listener «поднят», но постов не видит — ни события в таймлайне, ни коммента
    (главный симптом «ничего не происходит»). Вступаем идемпотентно (повторный
    JoinChannel на уже-вступившего безвреден) и заодно прогреваем entity-кэш
    сессии, чтобы последующий ``send_message(discussion_group_id)`` резолвил
    группу. Ошибку НЕ роняем: handler регистрируем в любом случае."""
    from telethon.tl.functions.channels import JoinChannelRequest

    from modules.commenting.worker.timeline import TimelineKind, push_event
    from worker.health import around_telethon_call

    async def _call(factory):
        return await around_telethon_call(
            factory,
            account_id=account_id,
            session_factory=ctx["session_factory"],
            publisher=ctx.get("publisher"),
        )

    try:
        disc_entity = await _resolve_discussion_entity(
            client, _call,
            channel_tg_id=channel_tg_id,
            discussion_group_id=discussion_group_id,
        )
        await _call(lambda: client(JoinChannelRequest(disc_entity)))
        get_logger().info(
            "commenting.channel_listener.joined_discussion",
            account_id=account_id,
            discussion_group_id=discussion_group_id,
        )
    except Exception as exc:  # noqa: BLE001 — join best-effort, attach не рушим
        get_logger().warning(
            "commenting.channel_listener.join_discussion_failed",
            account_id=account_id,
            discussion_group_id=discussion_group_id,
            error=repr(exc),
        )
        if source_campaign_id is not None:
            push_event(
                redis, source_campaign_id, TimelineKind.LISTENER_OFFLINE,
                f"Не удалось вступить в группу обсуждений канала «{channel_ref or ''}» "
                f"аккаунтом #{account_id} — посты могут не ловиться. "
                f"({type(exc).__name__})",
                meta={
                    "reason": "join_discussion_failed",
                    "discussion_group_id": discussion_group_id,
                },
            )


class ListenerRegistry:
    """Реестр активных слушателей: campaign_id → подключённый handler.

    Потокобезопасность в рамках event loop обеспечивает ``asyncio.Lock`` —
    attach/detach одной кампании сериализуются, чтобы не возникло двух
    слушателей или гонки attach/detach.
    """

    def __init__(self) -> None:
        self._handlers: dict[int, _Attached] = {}
        self._cursor: dict[int, int] = {}
        self._lock = asyncio.Lock()

    def active(self) -> list[int]:
        """id кампаний с подключённым слушателем."""
        return sorted(self._handlers)

    def is_attached(self, campaign_id: int) -> bool:
        return campaign_id in self._handlers

    async def load_all(self, ctx: dict) -> list[int]:
        """Подключает слушателей ко ВСЕМ enabled-кампаниям (вызов при старте).

        Требует готовый ``ctx['client_pool']`` — поэтому вызывается в startup
        строго ПОСЛЕ того, как пул положен в ctx.
        """
        session_factory = ctx["session_factory"]
        with session_factory() as session:
            enabled = [c.id for c in CampaignRepository(session).list_all() if c.enabled]
        for campaign_id in enabled:
            await self.attach(campaign_id, ctx)
        started = self.active()
        get_logger().info("commenting.listener.load_all", campaigns=started)
        return started

    async def attach(self, campaign_id: int, ctx: dict) -> bool:
        """Подключает слушатель одной кампании. Идемпотентно (повтор — no-op).

        Возвращает True, если слушатель активен после вызова; False — если
        кампания не enabled / нет assigned-аккаунтов (подключать нечем/незачем).
        """
        from telethon import events

        async with self._lock:
            if campaign_id in self._handlers:
                return True  # уже подключён — повторное событие безопасно

            session_factory = ctx["session_factory"]
            pool = ctx["client_pool"]
            task_queue = _task_queue(ctx)

            # Локальный импорт: timeline → structlog, structlog → ... циклов нет,
            # но делаем здесь, чтобы push в error-веткaх был доступен.
            from modules.commenting.worker.timeline import TimelineKind, push_event
            redis = _timeline_redis(ctx)

            with session_factory() as session:
                campaign = CampaignRepository(session).get(campaign_id)
                if campaign is None or not campaign.enabled:
                    get_logger().info(
                        "commenting.listener.attach.skip",
                        campaign_id=campaign_id,
                        reason="missing_or_disabled",
                    )
                    push_event(
                        redis, campaign_id, TimelineKind.LISTENER_OFFLINE,
                        "Слушатель не поднят: кампания выключена или удалена",
                        meta={"reason": "missing_or_disabled"},
                    )
                    return False
                # В режиме «по подпискам аккаунта» этот кампанийный listener
                # не используется — слушатели живут на уровне каждой подписки
                # аккаунта (ChannelListenerRegistry), а target_channel/
                # discussion_group_id на самой кампании вообще не задаются
                # (поле target_channel помечено как «легаси»). Если попали
                # сюда в этом режиме — просто тихо выходим, без error-плашек.
                # getattr: тесты в test_commenting_lifecycle используют
                # SimpleNamespace без channel_source_mode; дефолт — старый режим.
                if getattr(campaign, "channel_source_mode", "explicit_links") == "by_account_subscriptions":
                    get_logger().info(
                        "commenting.listener.attach.skip",
                        campaign_id=campaign_id,
                        reason="by_account_subscriptions",
                    )
                    return False
                target_channel = campaign.target_channel
                discussion_group_id = campaign.discussion_group_id
                account = await round_robin_account(session, campaign_id, self._cursor)

            if account is None:
                get_logger().warning(
                    "commenting.listener.attach.no_account", campaign_id=campaign_id
                )
                push_event(
                    redis, campaign_id, TimelineKind.NO_ACCOUNT,
                    "Слушатель не поднят: нет аккаунта в статусе assigned. "
                    "Прикрепите хотя бы один аккаунт к кампании.",
                    meta={"reason": "no_account"},
                )
                return False

            if not target_channel:
                get_logger().warning(
                    "commenting.listener.attach.no_target", campaign_id=campaign_id
                )
                push_event(
                    redis, campaign_id, TimelineKind.LISTENER_OFFLINE,
                    "Слушатель не поднят: у кампании не указан target_channel.",
                    meta={"reason": "no_target_channel"},
                )
                return False

            if discussion_group_id is None:
                get_logger().warning(
                    "commenting.listener.attach.no_discussion",
                    campaign_id=campaign_id, target=target_channel,
                )
                push_event(
                    redis, campaign_id, TimelineKind.LISTENER_OFFLINE,
                    f"Слушатель не поднят: у канала «{target_channel}» нет группы обсуждений. "
                    "Включите обсуждения в самом Telegram-канале (Discussion group) "
                    "или укажите канал, где обсуждения уже подключены.",
                    meta={"reason": "no_discussion_group", "target_channel": target_channel},
                )
                return False

            try:
                client = await pool.get(account.id)
                channel = await client.get_entity(target_channel)
                channel_id = getattr(channel, "id", None)
            except Exception as exc:  # noqa: BLE001
                get_logger().warning(
                    "commenting.listener.attach.resolve_failed",
                    campaign_id=campaign_id, target=target_channel, error=repr(exc),
                )
                push_event(
                    redis, campaign_id, TimelineKind.LISTENER_OFFLINE,
                    f"Слушатель не поднят: не удалось открыть канал «{target_channel}» "
                    f"аккаунтом #{account.id}. Проверьте, что аккаунт подписан и "
                    f"у него есть доступ. ({type(exc).__name__})",
                    meta={"reason": "resolve_failed", "error": repr(exc)[:200]},
                )
                return False

            handler = make_new_post_handler(
                campaign_id,
                task_queue,
                channel_id=channel_id,
                session_factory=session_factory,
                redis=redis,
            )
            event = events.NewMessage(chats=discussion_group_id)
            client.add_event_handler(handler, event)
            self._handlers[campaign_id] = _Attached(
                client=client,
                handler=handler,
                event=event,
                pool=pool,
                account_id=account.id,
            )
            get_logger().info(
                "commenting.listener.attach",
                campaign_id=campaign_id,
                account_id=account.id,
            )
            push_event(
                redis, campaign_id, TimelineKind.LISTENER_ONLINE,
                f"Слушатель канала подключён (аккаунт #{account.id})",
                meta={
                    "account_id": account.id,
                    "discussion_group_id": discussion_group_id,
                    "channel_id": channel_id,
                },
            )
            return True

    async def detach(self, campaign_id: int) -> bool:
        """Отключает слушатель кампании: снимает handler и отпускает клиента.

        Возвращает True, если слушатель был активен и снят; False — если такого
        слушателя не было (повторный/лишний detach безопасен).
        """
        async with self._lock:
            attached = self._handlers.pop(campaign_id, None)
            if attached is None:
                return False
            try:
                attached.client.remove_event_handler(attached.handler, attached.event)
            finally:
                await attached.pool.release(attached.account_id)
            get_logger().info("commenting.listener.detach", campaign_id=campaign_id)
            return True

    async def close_all(self) -> None:
        """Снимает все слушатели (shutdown)."""
        for campaign_id in self.active():
            await self.detach(campaign_id)


class CampaignLifecycleListener:
    """Фоновая подписка на ``campaign_lifecycle`` → attach/detach через реестр.

    Держит собственное async-соединение с Redis (как :class:`LoginEventHub`),
    чтобы не конкурировать с транспортом задач arq. Цикл ``run`` работает пока
    задачу не отменят (``stop``) — то есть весь срок жизни воркера.
    """

    def __init__(
        self,
        registry: ListenerRegistry,
        ctx: dict,
        redis_url: str,
        channel: str = CAMPAIGN_LIFECYCLE_CHANNEL,
    ) -> None:
        self._registry = registry
        self._ctx = ctx
        self._redis_url = redis_url
        self._channel = channel
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Any = None

    async def run(self) -> None:
        """Подписывается и вечно обрабатывает события (до отмены задачи)."""
        self._redis = aioredis.from_url(self._redis_url)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._channel)
        get_logger().info("commenting.lifecycle.subscribed", channel=self._channel)
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            await self._handle(message.get("data"))

    async def _handle(self, data: Any) -> None:
        if isinstance(data, (bytes, bytearray)):
            data = data.decode()
        try:
            payload = json.loads(data)
        except (TypeError, ValueError):
            return
        campaign_id = payload.get("campaign_id")
        action = payload.get("action")
        if campaign_id is None or action not in (ACTION_ATTACH, ACTION_DETACH):
            return
        try:
            if action == ACTION_ATTACH:
                await self._registry.attach(int(campaign_id), self._ctx)
            else:
                await self._registry.detach(int(campaign_id))
        except Exception as exc:  # noqa: BLE001 - событие не должно ронять цикл
            get_logger().warning(
                "commenting.lifecycle.handle_failed",
                campaign_id=campaign_id,
                action=action,
                error=repr(exc),
            )

    async def stop(self) -> None:
        """Закрывает pub/sub-соединение (под таймаутами, как в LoginEventHub)."""
        if self._pubsub is not None:
            try:
                await asyncio.wait_for(self._pubsub.aclose(), timeout=2.0)
            except Exception:
                pass
            self._pubsub = None
        if self._redis is not None:
            try:
                await asyncio.wait_for(self._redis.aclose(), timeout=2.0)
            except Exception:
                pass
            self._redis = None


def publish_campaign_lifecycle(publisher: Any, campaign_id: int, action: str) -> None:
    """Публикует событие жизненного цикла кампании (no-op, если publisher=None).

    Единая точка формирования payload ``{campaign_id, action}`` для API-роутов.
    """
    if publisher is None:
        return
    publisher.publish(
        CAMPAIGN_LIFECYCLE_CHANNEL, {"campaign_id": campaign_id, "action": action}
    )


def publish_channel_lifecycle(
    publisher: Any, account_id: int, channel_id: int, action: str
) -> None:
    """Публикует ``{account_id, channel_id, action}`` в ``channel_lifecycle``.

    Единая точка для API-роутов каналов (worker публикует симметрично из
    ``channels.publish_channel_lifecycle``). no-op при publisher=None.
    """
    if publisher is None:
        return
    publisher.publish(
        CHANNEL_LIFECYCLE_CHANNEL,
        {"account_id": account_id, "channel_id": channel_id, "action": action},
    )


# --- аккаунт-центричный мониторинг каналов -----------------------------------


@dataclass
class _AccountChannels:
    """Один Telethon-клиент аккаунта + его handler'ы по working-каналам."""

    client: Any
    pool: Any
    handlers: dict  # monitored_channel_id -> (handler, event)


class ChannelListenerRegistry:
    """Реестр слушателей каналов аккаунтов: monitored_channel_id → handler.

    У каждого аккаунта один клиент (из пула), на нём висят handler'ы по числу его
    working-каналов. Клиент держится, пока у аккаунта есть хотя бы один активный
    канал, и возвращается в пул, когда снят последний. Динамика — через
    :class:`ChannelLifecycleListener` (Redis ``channel_lifecycle``), без рестарта.
    """

    def __init__(self) -> None:
        self._accounts: dict[int, _AccountChannels] = {}
        self._channel_account: dict[int, int] = {}
        self._lock = asyncio.Lock()

    def active(self) -> list[int]:
        """id каналов с подключённым слушателем."""
        return sorted(self._channel_account)

    def is_attached(self, channel_id: int) -> bool:
        return channel_id in self._channel_account

    async def load_all(self, ctx: dict) -> list[int]:
        """Подключает слушатели ко ВСЕМ working-каналам assigned-аккаунтов."""
        session_factory = ctx["session_factory"]
        with session_factory() as session:
            repo = MonitoredChannelRepository(session)
            links = CampaignAccountRepository(session)
            campaigns = CampaignRepository(session)
            accounts = AccountRepository(session)
            candidates: list[int] = []
            for ch in repo.list_all_working():
                if ch.discussion_group_id is None:
                    continue
                account = accounts.get(ch.account_id)
                if account is None or account.status != "assigned":
                    continue
                link = links.get_by_account(ch.account_id)
                if link is None:
                    continue
                campaign = campaigns.get(link.campaign_id)
                if campaign is None or not campaign.enabled:
                    continue
                candidates.append(ch.id)
        for channel_id in candidates:
            await self.attach(channel_id, ctx)
        started = self.active()
        get_logger().info("commenting.channel_listener.load_all", channels=started)
        return started

    async def attach(self, channel_id: int, ctx: dict) -> bool:
        """Подключает слушатель одного канала. Идемпотентно."""
        from telethon import events

        from modules.commenting.worker.timeline import TimelineKind, push_event

        redis = _timeline_redis(ctx)
        async with self._lock:
            if channel_id in self._channel_account:
                return True

            session_factory = ctx["session_factory"]
            pool = ctx["client_pool"]
            task_queue = _task_queue(ctx)

            with session_factory() as session:
                ch = MonitoredChannelRepository(session).get(channel_id)
                if ch is None:
                    get_logger().info(
                        "commenting.channel_listener.attach.skip",
                        channel_id=channel_id,
                        reason="missing",
                    )
                    return False
                source_campaign_id = ch.source_campaign_id
                channel_ref = ch.channel_ref or ch.input_ref
                if ch.status != "working":
                    get_logger().info(
                        "commenting.channel_listener.attach.skip",
                        channel_id=channel_id,
                        reason=f"status={ch.status}",
                    )
                    if source_campaign_id is not None:
                        push_event(
                            redis, source_campaign_id, TimelineKind.LISTENER_OFFLINE,
                            f"Канал «{channel_ref}» не в работе (status={ch.status}). "
                            f"Проверьте что аккаунт подписан и канал резолвится.",
                            meta={
                                "reason": "not_working",
                                "channel_id": channel_id,
                                "status": ch.status,
                                "error": ch.error,
                            },
                        )
                    return False
                if ch.discussion_group_id is None:
                    get_logger().info(
                        "commenting.channel_listener.attach.skip",
                        channel_id=channel_id,
                        reason="no_discussion",
                    )
                    if source_campaign_id is not None:
                        push_event(
                            redis, source_campaign_id, TimelineKind.LISTENER_OFFLINE,
                            f"У канала «{channel_ref}» нет группы обсуждений. "
                            "Включите Discussion group в самом Telegram-канале.",
                            meta={
                                "reason": "no_discussion_group",
                                "channel_id": channel_id,
                            },
                        )
                    return False
                account_id = ch.account_id
                discussion_group_id = ch.discussion_group_id
                channel_tg_id = ch.channel_tg_id

            entry = self._accounts.get(account_id)
            if entry is None:
                client = await pool.get(account_id)
                entry = _AccountChannels(client=client, pool=pool, handlers={})
                self._accounts[account_id] = entry

            # Без членства в discussion-группе Telethon не отдаёт её апдейты —
            # handler ниже не сработает ни на один пост. Вступаем best-effort.
            await _ensure_joined_discussion(
                ctx, entry.client,
                account_id=account_id,
                channel_tg_id=channel_tg_id,
                discussion_group_id=discussion_group_id,
                channel_ref=channel_ref,
                source_campaign_id=source_campaign_id,
                redis=redis,
            )

            handler = make_channel_post_handler(
                account_id, channel_id, task_queue,
                channel_tg_id=channel_tg_id,
                redis=redis,
                source_campaign_id=source_campaign_id,
                channel_ref=channel_ref,
            )
            event = events.NewMessage(chats=discussion_group_id)
            entry.client.add_event_handler(handler, event)
            entry.handlers[channel_id] = (handler, event)
            self._channel_account[channel_id] = account_id
            get_logger().info(
                "commenting.channel_listener.attach",
                channel_id=channel_id,
                account_id=account_id,
            )
            if source_campaign_id is not None:
                push_event(
                    redis, source_campaign_id, TimelineKind.LISTENER_ONLINE,
                    f"Слушатель канала «{channel_ref}» подключён (аккаунт #{account_id})",
                    meta={
                        "channel_id": channel_id,
                        "account_id": account_id,
                        "discussion_group_id": discussion_group_id,
                    },
                )
            return True

    async def detach(self, channel_id: int) -> bool:
        """Снимает слушатель канала; отпускает клиента, если он был последним."""
        async with self._lock:
            account_id = self._channel_account.pop(channel_id, None)
            if account_id is None:
                return False
            entry = self._accounts.get(account_id)
            if entry is None:
                return False
            handler, event = entry.handlers.pop(channel_id, (None, None))
            if handler is not None:
                entry.client.remove_event_handler(handler, event)
            if not entry.handlers:
                self._accounts.pop(account_id, None)
                await entry.pool.release(account_id)
            get_logger().info(
                "commenting.channel_listener.detach",
                channel_id=channel_id,
                account_id=account_id,
            )
            return True

    async def close_all(self) -> None:
        """Снимает все слушатели каналов (shutdown)."""
        for channel_id in self.active():
            await self.detach(channel_id)


class ChannelLifecycleListener:
    """Фоновая подписка на ``channel_lifecycle`` → attach/detach каналов.

    payload ``{account_id, channel_id, action: attach|detach}``: resolve_channel
    публикует ``attach`` после успешной подписки, DELETE /channels — ``detach``.
    Живёт весь срок процесса воркера (как :class:`CampaignLifecycleListener`).
    """

    def __init__(
        self,
        registry: "ChannelListenerRegistry",
        ctx: dict,
        redis_url: str,
        channel: str = CHANNEL_LIFECYCLE_CHANNEL,
    ) -> None:
        self._registry = registry
        self._ctx = ctx
        self._redis_url = redis_url
        self._channel = channel
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Any = None

    async def run(self) -> None:
        self._redis = aioredis.from_url(self._redis_url)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._channel)
        get_logger().info("commenting.channel_lifecycle.subscribed", channel=self._channel)
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            await self._handle(message.get("data"))

    async def _handle(self, data: Any) -> None:
        if isinstance(data, (bytes, bytearray)):
            data = data.decode()
        try:
            payload = json.loads(data)
        except (TypeError, ValueError):
            return
        channel_id = payload.get("channel_id")
        action = payload.get("action")
        if channel_id is None or action not in (ACTION_ATTACH, ACTION_DETACH):
            return
        try:
            if action == ACTION_ATTACH:
                await self._registry.attach(int(channel_id), self._ctx)
            else:
                await self._registry.detach(int(channel_id))
        except Exception as exc:  # noqa: BLE001 - событие не должно ронять цикл
            get_logger().warning(
                "commenting.channel_lifecycle.handle_failed",
                channel_id=channel_id,
                action=action,
                error=repr(exc),
            )

    async def stop(self) -> None:
        if self._pubsub is not None:
            try:
                await asyncio.wait_for(self._pubsub.aclose(), timeout=2.0)
            except Exception:
                pass
            self._pubsub = None
        if self._redis is not None:
            try:
                await asyncio.wait_for(self._redis.aclose(), timeout=2.0)
            except Exception:
                pass
            self._redis = None
