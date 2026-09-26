"""Разрешение и подписка на каналы аккаунта (аккаунт-центричный мониторинг).

Каждый аккаунт держит свой список каналов (:class:`MonitoredChannel`). Задачи
здесь превращают «сырой» ввод пользователя (ссылка на канал / @username / инвайт
/ ссылка на папку-addlist) в реальную подписку через Telethon и заполняют
техполя строки (``channel_tg_id``, ``discussion_group_id``, ``title``), после
чего канал переходит в статус ``working`` и слушатель начинает ловить в нём посты
(см. :mod:`modules.commenting.worker.registry`).

Тела задач:
- ``resolve_channel`` — вступить/подписаться и разрешить discussion-группу; для
  папки — развернуть в дочерние строки и поставить их в очередь на resolve;
- ``leave_channel`` — отписаться (LeaveChannel), опция ``?unsubscribe=true`` в API.

Разрешение ссылок и join — единственное место, где модуль трогает Telethon
напрямую; всё обёрнуто в :func:`around_telethon_call` (health-инциденты, flood).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from modules.commenting.repositories import MonitoredChannelRepository
from modules.commenting.worker.alerts import raise_alert, resolve_alerts
from worker.client_pool import ClientPool
from worker.health import around_telethon_call
from worker.telegram_folders import join_folder
from worker.telegram_refs import folder_slug, invite_hash, public_ref, strip_url

get_logger = structlog.get_logger

CHANNEL_LIFECYCLE_CHANNEL = "channel_lifecycle"
ACTION_ATTACH = "attach"
ACTION_DETACH = "detach"


# --- ctx-инъекции (как в runner) ---------------------------------------------


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


# --- разбор пользовательского ввода ------------------------------------------
# Реюз helper'ов из worker.telegram_refs (этап 8, backlog #1): раньше здесь
# были локальные копии, что грозило дрейфом. Сохраняем короткие псевдонимы,
# чтобы диффы вызовов остались точечными.
_strip_url = strip_url
_folder_slug = folder_slug
_invite_hash = invite_hash
_public_ref = public_ref


# --- resolve_channel ---------------------------------------------------------


class NotSubscribed(Exception):
    """Аккаунт не подписан на канал, а политика запрещает вступать (notify_only)."""


async def _join_and_resolve(
    client: Any,
    input_ref: str,
    *,
    account_id: int,
    session_factory,
    publisher,
    now,
    allow_join: bool = True,
) -> tuple[dict, bool]:
    """Разрешает канал и его discussion-группу; при необходимости вступает.

    Сначала проверяем членство БЕЗ вступления (инвайт — CheckChatInvite,
    публичный — ``entity.left``). Не подписан и ``allow_join=False`` →
    :class:`NotSubscribed`. Возвращает (техполя, joined) — joined=True, если
    вступили именно сейчас.
    """
    from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
    from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
    from telethon.tl.types import ChatInviteAlready

    invite = _invite_hash(input_ref)

    async def _call(coro_factory):
        return await around_telethon_call(
            coro_factory,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )

    joined = False
    if invite is not None:
        info = await _call(lambda: client(CheckChatInviteRequest(invite)))
        if isinstance(info, ChatInviteAlready):
            entity = info.chat
        else:
            if not allow_join:
                raise NotSubscribed(input_ref)
            updates = await _call(lambda: client(ImportChatInviteRequest(invite)))
            chats = getattr(updates, "chats", None) or []
            entity = chats[0] if chats else None
            joined = True
    else:
        ref = _public_ref(input_ref)
        entity = await _call(lambda: client.get_entity(ref))
        was_member = not getattr(entity, "left", False)
        if not was_member and not allow_join:
            raise NotSubscribed(input_ref)
        if allow_join:
            # Join идемпотентен — зовём всегда, как и раньше (у ручных каналов
            # entity.left может быть неизвестен).
            await _call(lambda: client(JoinChannelRequest(entity)))
            joined = not was_member

    if entity is None:
        raise RuntimeError(f"cannot resolve entity for {input_ref!r}")

    full = await _call(lambda: client(GetFullChannelRequest(entity)))
    linked = getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
    return {
        "channel_ref": getattr(entity, "username", None) or _public_ref(input_ref),
        "channel_tg_id": getattr(entity, "id", None),
        "title": getattr(entity, "title", None),
        "discussion_group_id": linked,
    }, joined


def _campaign_get(session, campaign_id: int):
    from modules.commenting.repositories import CampaignRepository

    return CampaignRepository(session).get(campaign_id)


def _channel_policy(session, source_campaign_id: Optional[int]) -> tuple[Optional[int], str]:
    """(campaign_id, policy) для строки мониторинга.

    policy: ``join`` — вступать молча (каналы, добавленные вручную на аккаунте,
    как раньше); ``join_notify`` — вступить и уведомить; ``notify`` — не
    вступать, только уведомить (campaigns.on_not_subscribed_action).
    """
    if source_campaign_id is None:
        return None, "join"
    from modules.commenting.repositories import CampaignRepository

    campaign = CampaignRepository(session).get(source_campaign_id)
    if campaign is None:
        return None, "join"
    if campaign.on_not_subscribed_action == "notify_only":
        return campaign.id, "notify"
    return campaign.id, "join_notify"


async def _resolve_folder(
    client: Any, slug: str, *, account_id: int, session_factory, publisher, now
) -> list[str]:
    """Вступает в папку-addlist и возвращает ref'ы каналов из неё.

    Тонкая обёртка над :func:`worker.telegram_folders.join_folder` — reuse
    после этапа 8, backlog #4 (helper вынесен, повторение кода убрано).
    ``now`` сохраняется в сигнатуре для обратной совместимости, но не
    прокидывается: around_telethon_call вычисляет ``now`` сам.
    """
    result = await join_folder(
        client,
        slug,
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
    )
    return result.joined_refs


async def resolve_channel(ctx: dict, channel_id: int) -> str:
    """Разрешает один :class:`MonitoredChannel`: подписка + discussion-группа.

    Для папки — разворачивает в дочерние строки и ставит их на resolve. При
    ошибке помечает строку ``failed`` (пользователь видит текст в UI).
    """
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    now = _now(ctx)
    log = get_logger()

    with session_factory() as session:
        ch = MonitoredChannelRepository(session).get(channel_id)
        if ch is None:
            return "missing"
        account_id = ch.account_id
        input_ref = ch.input_ref
        is_folder = ch.is_folder
        source_campaign_id = ch.source_campaign_id
        campaign_id, policy = _channel_policy(session, source_campaign_id)

    if is_folder and policy == "notify":
        # Развернуть папку можно только вступив в неё — при «только
        # уведомлять» не вступаем, а сообщаем пользователю.
        with session_factory() as session:
            MonitoredChannelRepository(session).mark_failed(channel_id, "not_subscribed")
            session.commit()
            raise_alert(
                session, publisher, campaign_id=campaign_id, account_id=account_id,
                channel_ref=input_ref, kind="not_subscribed",
                detail="Папку можно развернуть только подписавшись — включите «Подписаться + уведомить».",
            )
        return "not_subscribed"

    pool = _pool(ctx)
    client = None
    try:
        # get() внутри try: битая сессия/прокси (CryptoError и т.п.) должна
        # помечать канал failed с текстом, а не оставлять его навсегда pending.
        client = await pool.get(account_id)
        if is_folder:
            slug = _folder_slug(input_ref)
            if slug is None:
                raise RuntimeError(f"not a folder link: {input_ref!r}")
            child_refs = await _resolve_folder(
                client, slug, account_id=account_id,
                session_factory=session_factory, publisher=publisher, now=now,
            )
            children: list[int] = []
            with session_factory() as session:
                repo = MonitoredChannelRepository(session)
                for ref in child_refs:
                    if repo.get_by_account_input(account_id, ref) is not None:
                        continue
                    child = repo.create(account_id, ref, is_folder=False)
                    # Дочерние каналы папки кампании — тоже «кампанийные».
                    child.source_campaign_id = source_campaign_id
                    children.append(child.id)
                # Папка-строка выполнила роль контейнера — помечаем working.
                repo.mark_working(
                    channel_id, channel_ref=slug, channel_tg_id=None,
                    title=f"Папка: {len(child_refs)} каналов",
                    discussion_group_id=None, subscribed=True,
                )
                session.commit()
            task_queue = _task_queue(ctx)
            for child_id in children:
                await task_queue.enqueue(
                    TaskName.COMMENTING_RESOLVE_CHANNEL, child_id
                )
            log.info(
                "commenting.resolve_channel.folder",
                channel_id=channel_id, children=len(children),
            )
            return "folder"

        try:
            info, joined = await _join_and_resolve(
                client, input_ref, account_id=account_id,
                session_factory=session_factory, publisher=publisher, now=now,
                allow_join=policy != "notify",
            )
        except NotSubscribed:
            with session_factory() as session:
                MonitoredChannelRepository(session).mark_failed(channel_id, "not_subscribed")
                session.commit()
                raise_alert(
                    session, publisher, campaign_id=campaign_id, account_id=account_id,
                    channel_ref=input_ref, kind="not_subscribed",
                    detail="Аккаунт не подписан на канал; кампания настроена только уведомлять.",
                )
            log.info("commenting.resolve_channel.not_subscribed", channel_id=channel_id)
            return "not_subscribed"
        with session_factory() as session:
            MonitoredChannelRepository(session).mark_working(channel_id, **info)
            session.commit()
            # Канал заработал — открытые «не подписан»/«нет доступа» больше не актуальны.
            resolve_alerts(session, account_id=account_id, channel_ref=input_ref)
            if joined and policy == "join_notify":
                raise_alert(
                    session, publisher, campaign_id=campaign_id, account_id=account_id,
                    channel_ref=input_ref, kind="auto_subscribed",
                    detail="Аккаунт не был подписан — подписали автоматически.",
                )
        publish_channel_lifecycle(publisher, account_id, channel_id, ACTION_ATTACH)
        # Кампания с post_scope in (existing, mixed) — прогуляемся по истории
        # канала (E2.1); отдельная задача, чтобы не блокировать resolve.
        if campaign_id is not None:
            with session_factory() as session:
                campaign = _campaign_get(session, campaign_id)
                needs_backfill = (
                    campaign is not None
                    and campaign.enabled
                    and campaign.post_scope in ("existing", "mixed")
                )
            if needs_backfill:
                await _task_queue(ctx).enqueue(
                    TaskName.COMMENTING_BACKFILL_CHANNEL, account_id, channel_id
                )
        log.info(
            "commenting.resolve_channel.working",
            channel_id=channel_id, account_id=account_id,
            discussion_group_id=info.get("discussion_group_id"),
        )
        return "working"
    except Exception as exc:  # noqa: BLE001 - ошибку показываем пользователю в UI
        with session_factory() as session:
            MonitoredChannelRepository(session).mark_failed(channel_id, repr(exc))
            session.commit()
        log.warning(
            "commenting.resolve_channel.failed",
            channel_id=channel_id, error=repr(exc),
        )
        return "failed"
    finally:
        if client is not None:
            await pool.release(account_id)


# --- синхронизация целевых каналов кампании (E3.2) ----------------------------

# Сколько каналов из подписок аккаунта берём максимум и пауза между
# GetFullChannel — чтобы разбор подписок не ловил FloodWait.
SUBSCRIPTIONS_MAX = 200
SUBSCRIPTIONS_PAUSE_SEC = (1.0, 3.0)


def _campaign_account_ids(session, campaign_id: int) -> list[int]:
    from core.repositories.account import AccountRepository
    from modules.commenting.repositories import CampaignAccountRepository

    ids = []
    accounts = AccountRepository(session)
    for link in CampaignAccountRepository(session).list_by_campaign(campaign_id):
        acc = accounts.get(link.account_id)
        if acc is not None and acc.status == "assigned":
            ids.append(acc.id)
    return ids


def _drop_rows(session, publisher, rows) -> None:
    """Удаляет «кампанийные» строки мониторинга и снимает их слушатели."""
    detach = [(r.account_id, r.id) for r in rows if r.status == "working"]
    for r in rows:
        session.delete(r)
    session.commit()
    for account_id, channel_id in detach:
        publish_channel_lifecycle(publisher, account_id, channel_id, ACTION_DETACH)


async def sync_campaign_channels(ctx: dict, campaign_id: int) -> dict:
    """Приводит мониторинг аккаунтов кампании к её настройкам целевых каналов.

    Идемпотентна — вызывается после любой правки (привязка/отвязка аккаунта,
    добавление/удаление ссылки, смена режима или политики, включение).

    * ``explicit_links``: каждому аккаунту — строка на каждую ссылку кампании
      (``source_campaign_id``); лишние «кампанийные» строки удаляются; строки
      в ``failed`` переразрешаются (например, после смены политики на
      «подписаться»). Ручные каналы аккаунта не трогаем.
    * ``by_account_subscriptions``: у каждого аккаунта разбираем его подписки
      (задача ``sync_account_subscriptions``); строки ушедших аккаунтов удаляем.
    * Кампания выключена/удалена — снимаем все её строки.
    """
    from modules.commenting.models import MonitoredChannel
    from modules.commenting.repositories import CampaignChannelRepository, CampaignRepository

    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    task_queue = _task_queue(ctx)
    to_resolve: list[int] = []
    subs_accounts: list[int] = []

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        owned = (
            session.query(MonitoredChannel)
            .filter(MonitoredChannel.source_campaign_id == campaign_id)
            .all()
        )
        if campaign is None or not campaign.enabled:
            _drop_rows(session, publisher, owned)
            return {"removed": len(owned), "resolve": 0}

        account_ids = _campaign_account_ids(session, campaign_id)
        repo = MonitoredChannelRepository(session)
        stale = [r for r in owned if r.account_id not in account_ids]

        if campaign.channel_source_mode == "explicit_links":
            links = CampaignChannelRepository(session).list_by_campaign(campaign_id)
            wanted = {(a, l.raw_input): l for a in account_ids for l in links}
            # Дочерние каналы папок тоже «кампанийные», но их нет в links —
            # держим их, пока в кампании есть хоть одна папка.
            has_folder = any(l.kind == "folder" for l in links)
            for r in owned:
                if r in stale:
                    continue
                if (r.account_id, r.input_ref) not in wanted and not (has_folder and not r.is_folder):
                    stale.append(r)
            for (account_id, raw), link in wanted.items():
                row = repo.get_by_account_input(account_id, raw)
                if row is None:
                    row = repo.create(account_id, raw, is_folder=link.kind == "folder")
                    row.source_campaign_id = campaign_id
                    session.flush()
                    to_resolve.append(row.id)
                elif row.source_campaign_id == campaign_id and row.status == "failed":
                    row.status = "pending"
                    row.error = None
                    to_resolve.append(row.id)
                # Ручная строка аккаунта с той же ссылкой уже мониторится — не дублируем.
            session.commit()
        else:
            subs_accounts = account_ids

        _drop_rows(session, publisher, stale)

    for channel_id in to_resolve:
        await task_queue.enqueue(TaskName.COMMENTING_RESOLVE_CHANNEL, channel_id)
    for account_id in subs_accounts:
        await task_queue.enqueue(
            TaskName.COMMENTING_SYNC_ACCOUNT_SUBSCRIPTIONS, account_id, campaign_id
        )
    get_logger().info(
        "commenting.sync_campaign_channels",
        campaign_id=campaign_id, resolve=len(to_resolve),
        subscriptions=len(subs_accounts), removed=len(stale),
    )
    return {"removed": len(stale), "resolve": len(to_resolve)}


async def sync_account_subscriptions(ctx: dict, account_id: int, campaign_id: int) -> int:
    """Режим «по подпискам аккаунта»: каналы, на которые аккаунт уже подписан.

    Берём диалоги аккаунта, оставляем каналы-трансляции с группой обсуждения
    (без неё комментировать некуда) и заводим по ним рабочие строки
    мониторинга (вступать не нужно — аккаунт уже в канале). Не больше
    ``SUBSCRIPTIONS_MAX`` каналов, с паузами между запросами.
    """
    import asyncio
    import random

    from telethon.tl.functions.channels import GetFullChannelRequest

    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    now = _now(ctx)
    rng = ctx.get("rng") or random.Random()
    sleep = ctx.get("sleep") or asyncio.sleep
    pool = _pool(ctx)

    async def _call(factory):
        return await around_telethon_call(
            factory, account_id=account_id, session_factory=session_factory,
            publisher=publisher, now=now,
        )

    with session_factory() as session:
        known = {r.channel_tg_id for r in MonitoredChannelRepository(session).list_by_account(account_id)}

    created = 0
    client = await pool.get(account_id)
    try:
        dialogs = await _call(lambda: client.get_dialogs(limit=None))
        for dialog in dialogs:
            if created >= SUBSCRIPTIONS_MAX:
                break
            ent = getattr(dialog, "entity", None)
            if not getattr(ent, "broadcast", False) or getattr(ent, "left", False):
                continue
            if ent.id in known:
                continue
            full = await _call(lambda: client(GetFullChannelRequest(ent)))
            linked = getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
            await sleep(rng.uniform(*SUBSCRIPTIONS_PAUSE_SEC))
            if not linked:
                continue  # комментарии в канале выключены
            ref = f"@{ent.username}" if getattr(ent, "username", None) else f"tg:{ent.id}"
            with session_factory() as session:
                repo = MonitoredChannelRepository(session)
                row = repo.create(account_id, ref, is_folder=False)
                row.source_campaign_id = campaign_id
                session.flush()
                repo.mark_working(
                    row.id,
                    channel_ref=getattr(ent, "username", None) or ref,
                    channel_tg_id=ent.id,
                    title=getattr(ent, "title", None),
                    discussion_group_id=linked,
                    subscribed=True,
                )
                session.commit()
                row_id = row.id
            known.add(ent.id)
            created += 1
            publish_channel_lifecycle(publisher, account_id, row_id, ACTION_ATTACH)
            # Кампания с post_scope in (existing, mixed) — уже подписанные
            # каналы тоже отбэкфилить (E2.1).
            with session_factory() as session:
                campaign = _campaign_get(session, campaign_id)
                if (
                    campaign is not None
                    and campaign.enabled
                    and campaign.post_scope in ("existing", "mixed")
                ):
                    await _task_queue(ctx).enqueue(
                        TaskName.COMMENTING_BACKFILL_CHANNEL, account_id, row_id
                    )
    finally:
        await pool.release(account_id)

    get_logger().info(
        "commenting.sync_account_subscriptions", account_id=account_id,
        campaign_id=campaign_id, created=created,
    )
    return created


# --- leave_channel -----------------------------------------------------------


async def leave_channel(
    ctx: dict, account_id: int, channel_ref: str, channel_tg_id: Optional[int] = None
) -> bool:
    """Отписывает аккаунт от канала (LeaveChannel). Ошибки не критичны."""
    from telethon.tl.functions.channels import LeaveChannelRequest

    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    now = _now(ctx)
    pool = _pool(ctx)
    client = None
    try:
        client = await pool.get(account_id)
        target: Any = channel_tg_id if channel_tg_id is not None else _public_ref(channel_ref)
        entity = await around_telethon_call(
            lambda: client.get_entity(target),
            account_id=account_id, session_factory=session_factory,
            publisher=publisher, now=now,
        )
        await around_telethon_call(
            lambda: client(LeaveChannelRequest(entity)),
            account_id=account_id, session_factory=session_factory,
            publisher=publisher, now=now,
        )
        get_logger().info(
            "commenting.leave_channel.done", account_id=account_id, channel=channel_ref
        )
        return True
    except Exception as exc:  # noqa: BLE001 - отписка best-effort
        get_logger().warning(
            "commenting.leave_channel.failed",
            account_id=account_id, channel=channel_ref, error=repr(exc),
        )
        return False
    finally:
        if client is not None:
            await pool.release(account_id)


# --- pub/sub жизненного цикла канала -----------------------------------------


def publish_channel_lifecycle(
    publisher: Any, account_id: int, channel_id: int, action: str
) -> None:
    """Публикует ``{account_id, channel_id, action}`` в ``channel_lifecycle``.

    Реестр слушателей (:mod:`registry`) реагирует attach/detach БЕЗ рестарта.
    no-op, если publisher=None (тесты/DEV без Redis).
    """
    if publisher is None:
        return
    publisher.publish(
        CHANNEL_LIFECYCLE_CHANNEL,
        {"account_id": account_id, "channel_id": channel_id, "action": action},
    )
