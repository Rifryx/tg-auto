"""Оркестратор кампании шиллинга (docs/neuroshilling-spec.md § 5.2, 5.3).

Пока реализован ``failover`` (промпт 4.3) — замена забаненного аккаунта на
резервный той же роли. ``start_campaign`` / ``process_target`` — промпт 4.4.

Инъекции через ctx: session_factory, task_queue, now, rng, publisher.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from modules.shilling.repositories import (
    BlacklistRepository,
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    ScenarioRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import BlacklistCreate, ExecutionLogCreate, TargetCreate
from worker.client_pool import ClientPool

get_logger = structlog.get_logger

_USABLE_ACCOUNT_STATUSES = {"pool", "assigned"}


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


# --- задача start_campaign ---------------------------------------------------


async def start_campaign(ctx: dict, campaign_id: int) -> int:
    """Валидирует кампанию и раскидывает цели по очереди с кулдауном.

    Возвращает число запланированных целей. При провале валидации переводит
    кампанию в status='error' и возвращает 0.
    """
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None:
            log.info("shilling.start.skip", campaign_id=campaign_id, reason="no_campaign")
            return 0
        if not campaign.enabled or campaign.status != "running":
            log.info("shilling.start.skip", campaign_id=campaign_id, reason="not_running")
            return 0

        ok, reason = _validate_ready(session, campaign)
        if not ok:
            CampaignRepository(session).set_status(campaign_id, "error")
            session.commit()
            log.warning("shilling.start.not_ready", campaign_id=campaign_id, reason=reason)
            return 0

        targets = CampaignTargetRepository(session).list_by_campaign(campaign_id)
        delay_lo = campaign.target_delay_min_sec
        delay_hi = campaign.target_delay_max_sec
        parallel = max(1, min(3, campaign.max_parallel_chats))
        # Цели в режиме «Мониторинг каналов» не планируем здесь: у них нет
        # конкретного поста, их подхватывает cron-поллер, когда в канале
        # выходит НОВЫЙ пост (см. poll_channel_monitors).
        target_ids = [t.id for t in targets if t.mode != "channel_monitor"]
        monitors = len(targets) - len(target_ids)

    # Темп. parallel=1 («По одному») — цели идут цепочкой: каждая следующая
    # стартует после паузы target_delay_*. parallel=2..3 — столько цепочек
    # одновременно, то есть пауза копится внутри каждой «дорожки» отдельно.
    #
    # Это планирование по времени, а не строгий семафор: мы не знаем заранее,
    # сколько проиграет диалог. Пауза между чатами задана пользователем именно
    # как запас поверх диалога — и в UI подписана как «пауза перед следующим
    # чатом», так что это честная интерпретация, а не приближение.
    lane_cursor = [0.0] * parallel
    for idx, target_id in enumerate(target_ids):
        lane = idx % parallel
        run_at = now + timedelta(seconds=lane_cursor[lane])
        await task_queue.schedule(
            TaskName.SHILLING_PROCESS_TARGET, run_at, campaign_id, target_id
        )
        lane_cursor[lane] += rng.uniform(delay_lo, delay_hi)

    log.info(
        "shilling.start.scheduled",
        campaign_id=campaign_id,
        targets=len(target_ids),
        monitors=monitors,
        parallel=parallel,
    )
    return len(target_ids)


def _validate_ready(session, campaign, *, require_targets: bool = True) -> tuple[bool, str]:
    """Минимальная проверка готовности (аналог API readiness, но без схем).

    ``require_targets=False`` для сухого прогона: он идёт по переданному
    тестовому чату, а не по целям кампании.
    """
    scenario = ScenarioRepository(session).get_by_campaign(campaign.id)
    if scenario is None:
        return False, "no_scenario"
    steps = ScenarioStepRepository(session).list_by_scenario(scenario.id)
    if not any(s.step_type == "message" for s in steps):
        return False, "no_message_steps"
    links = CampaignAccountRepository(session).list_by_campaign(campaign.id)
    primary = [link for link in links if not link.is_reserve]
    if len(primary) < scenario.persons_count:
        return False, "not_enough_accounts"
    if require_targets and not CampaignTargetRepository(session).list_by_campaign(campaign.id):
        return False, "no_targets"
    return True, ""


# --- задача process_target ---------------------------------------------------


async def process_target(
    ctx: dict, campaign_id: int, target_id: int, post_id: Optional[int] = None
) -> int:
    """Готовит цель (резолв + куда постить) и планирует шаги сценария.

    ``post_id`` — конкретный пост, перекрывающий ``target.post_id``. Его
    передаёт поллер мониторинга каналов: у цели-«монитора» своего поста нет,
    пост появляется в канале уже после её создания.

    Возвращает число запланированных шагов (0 — если цель пропущена).
    """
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None or not campaign.enabled or campaign.status != "running":
            log.info("shilling.process_target.skip", campaign_id=campaign_id, reason="not_running")
            return 0

        target = CampaignTargetRepository(session).get(target_id)
        if target is None or target.campaign_id != campaign_id:
            log.info("shilling.process_target.skip", target_id=target_id, reason="no_target")
            return 0

        # Чёрный список (по chat_id или username).
        username = target.raw_input if target.kind == "username" else None
        if BlacklistRepository(session).is_blacklisted(
            campaign_id, chat_id=target.resolved_chat_id, username=username
        ):
            log.info("shilling.process_target.skip", target_id=target_id, reason="blacklisted")
            return 0

        scenario = ScenarioRepository(session).get_by_campaign(campaign_id)
        if scenario is None:
            return 0
        steps = ScenarioStepRepository(session).list_by_scenario(scenario.id)
        message_or_reaction = [s for s in steps if s.step_type in ("message", "reaction")]
        if not message_or_reaction:
            return 0

        # Для «монитора» resolved_chat_id — это linked-группа канала (её
        # записал прошлый прогон), а резолвить нужно сам КАНАЛ: идём от
        # raw_input. Для остальных режимов resolved_chat_id — валидный короткий
        # путь без лишнего resolve-запроса.
        target_mode = target.mode
        target_is_auto = target.auto_discovered
        raw_ref = (
            target.raw_input
            if target_mode == "channel_monitor"
            else (target.resolved_chat_id or target.raw_input)
        )
        target_post_id = post_id if post_id is not None else target.post_id
        reply_lo = campaign.reply_delay_min_sec
        reply_hi = campaign.reply_delay_max_sec
        first_lo = campaign.first_reply_delay_min_sec
        first_hi = campaign.first_reply_delay_max_sec
        # Раздача ролей по аккаунтам на ЭТОТ чат. shuffle_lineup_between_chats
        # решает, тянем ли мы один и тот же состав везде или мешаем заново:
        # см. _assign_lineup.
        link_repo = CampaignAccountRepository(session)
        lineup = _assign_lineup(
            link_repo,
            campaign_id,
            [s.role_id for s in message_or_reaction],
            rng=rng,
            shuffle=campaign.shuffle_lineup_between_chats,
        )
        plan: list[tuple[int, Optional[int], Optional[int]]] = []  # (step_id, account_id, delay)
        for idx, step in enumerate(message_or_reaction):
            account_id = lineup.get(step.role_id)
            if account_id is None:
                log.info(
                    "shilling.process_target.step_skip",
                    step_id=step.id, reason="no_account_for_role",
                )
                continue
            delay = step.delay_before_sec
            if delay is None:
                # Первая реплика в чате — отдельная, куда более длинная пауза:
                # зайти и сразу заговорить это самый заметный паттерн.
                delay = (
                    rng.uniform(first_lo, first_hi)
                    if idx == 0
                    else rng.uniform(reply_lo, reply_hi)
                )
            plan.append((step.id, account_id, delay))

        # Аккаунт для резолва канала — любой primary.
        resolver_links = [
            link for link in link_repo.list_by_campaign(campaign_id) if not link.is_reserve
        ]
        resolver_account_id = resolver_links[0].account_id if resolver_links else None

    if not plan or resolver_account_id is None:
        log.info("shilling.process_target.skip", target_id=target_id, reason="empty_plan")
        return 0

    # Резолвим цель по её режиму: пишем прямо в чат или в комментарии под постом.
    pool = _pool(ctx)
    client = await pool.get(resolver_account_id)
    try:
        chat_id, root_msg_id = await _resolve_posting_target(
            client, raw_ref,
            mode=target_mode, post_id=target_post_id,
            account_id=resolver_account_id, session_factory=session_factory,
            publisher=publisher, now=now,
        )
    except Exception as exc:  # noqa: BLE001 — резолв упал → цель в ЧС
        await pool.release(resolver_account_id)
        with session_factory() as session:
            CampaignTargetRepository(session).mark_error(target_id, type(exc).__name__)
            _blacklist_target(session, campaign_id, target_id, reason=f"resolve failed: {type(exc).__name__}")
            session.commit()
        log.warning("shilling.process_target.resolve_failed", target_id=target_id, error=type(exc).__name__)
        return 0
    finally:
        await pool.release(resolver_account_id)

    if chat_id is None:
        # Авто-цель (из подписок аккаунта по тумблеру «мониторить всё») без
        # комментариев — не ошибка пользователя и не повод для ЧС: канал
        # просто без обсуждения. Тихо пропускаем, цель остаётся жить.
        if target_is_auto:
            log.info("shilling.process_target.skip", target_id=target_id, reason="auto_no_discussion")
            return 0
        # Для режимов с комментариями это значит «обсуждение закрыто»; для
        # mode='chat' — что ссылка вообще не резолвится в чат.
        reason = (
            "comments closed / no discussion"
            if target_mode in ("link", "channel_post", "channel_monitor")
            else "not a chat"
        )
        with session_factory() as session:
            CampaignTargetRepository(session).mark_error(target_id, "no_posting_target")
            _blacklist_target(session, campaign_id, target_id, reason=reason)
            session.commit()
        log.info("shilling.process_target.skip", target_id=target_id, reason=reason)
        return 0

    # Куда постим: discussion-группа (комментарии) либо сам чат (mode='chat').
    with session_factory() as session:
        CampaignTargetRepository(session).mark_resolved(
            target_id, resolved_chat_id=chat_id
        )
        session.commit()

    # Планируем шаги с накопительной задержкой; все reply к корню обсуждения.
    cumulative = 0.0
    for step_id, account_id, delay in plan:
        cumulative += float(delay)
        run_at = now + timedelta(seconds=cumulative)
        await task_queue.schedule(
            TaskName.SHILLING_EXECUTE_STEP,
            run_at,
            campaign_id,
            target_id,
            step_id,
            account_id,
            thread_msg_id=root_msg_id,
        )
    log.info(
        "shilling.process_target.scheduled",
        target_id=target_id, steps=len(plan), chat_id=chat_id, mode=target_mode,
    )
    return len(plan)


async def _resolve_posting_target(
    client: Any,
    raw_ref,
    *,
    mode: str = "link",
    post_id: Optional[int] = None,
    account_id: int,
    session_factory,
    publisher,
    now,
) -> tuple[Optional[int], Optional[int]]:
    """Куда и во что писать → ``(chat_id, root_msg_id)``.

    Ветвимся по режиму цели:

    * ``chat`` — пишем ПРЯМО в чат/группу: chat_id = сам чат, root_msg_id=None
      (executor отправит обычное сообщение, не реплай).
    * ``channel_post`` / ``channel_monitor`` — комментарии под КОНКРЕТНЫМ
      постом ``post_id``: chat_id = linked-группа канала, root_msg_id = корень
      треста обсуждения этого поста.
    * ``link`` — авто (прежнее поведение): если у канала есть обсуждение —
      комментируем последний пост; если ссылка ведёт в чат/группу без
      linked_chat — пишем прямо туда.

    ``chat_id is None`` означает «писать некуда» (комментарии закрыты либо
    ссылка не резолвится в чат) — вызывающий код уводит цель в ЧС.
    """
    from telethon.tl.functions.channels import GetFullChannelRequest
    from telethon.tl.functions.messages import GetDiscussionMessageRequest
    from worker.health import around_telethon_call

    async def _call(factory):
        return await around_telethon_call(
            factory, account_id=account_id, session_factory=session_factory,
            publisher=publisher, now=now,
        )

    entity = await _call(lambda: client.get_entity(raw_ref))

    # Прямая отправка в чат/группу — обсуждение не ищем вовсе.
    if mode == "chat":
        chat_id = getattr(entity, "id", None)
        return (int(chat_id) if chat_id is not None else None), None

    full = await _call(lambda: client(GetFullChannelRequest(entity)))
    linked = getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
    if linked is None:
        # У обычной группы/супергруппы linked_chat_id нет — в режиме `link`
        # это не ошибка: пишем прямо в неё (мегагруппа = чат). Для режимов с
        # явным постом это действительно «комментарии закрыты».
        if mode == "link" and getattr(entity, "megagroup", False):
            chat_id = getattr(entity, "id", None)
            return (int(chat_id) if chat_id is not None else None), None
        return None, None

    # Какой пост комментируем: указанный явно или последний в канале.
    target_post_id = post_id
    if target_post_id is None:
        posts = await _call(lambda: client.get_messages(entity, limit=1))
        if not posts:
            return linked, None
        target_post_id = getattr(posts[0], "id", None)
        if target_post_id is None:
            return linked, None

    disc = await _call(
        lambda: client(GetDiscussionMessageRequest(peer=entity, msg_id=target_post_id))
    )
    disc_messages = getattr(disc, "messages", None) or []
    root_msg_id = getattr(disc_messages[0], "id", None) if disc_messages else None
    return linked, root_msg_id


def _assign_lineup(
    link_repo,
    campaign_id: int,
    role_ids,
    *,
    rng: random.Random,
    shuffle: bool,
) -> dict[Optional[int], int]:
    """Раздаёт роли по аккаунтам для ОДНОГО чата → ``{role_id: account_id}``.

    ``shuffle=False`` (дефолт): роль играет тот аккаунт, который за ней
    закреплён в ``campaign_accounts.role_id``. Один и тот же аккаунт — одна и
    та же роль во всех чатах: диалог не разваливается, когда у учёток разные
    имя, пол и аватарка.

    ``shuffle=True``: роли раздаются заново случайными свободными аккаунтами
    кампании — не светим одну и ту же связку (Telegram банит связанные
    аккаунты пачкой). ЗАКРЕПЛЁННЫЕ роли не перемешиваются в любом случае:
    пользователь явно сказал, кто играет эту роль.

    Один аккаунт не получает две роли в одном чате — иначе он отвечал бы сам
    себе от двух «разных» участников в одном треде.
    """
    unique_roles = list(dict.fromkeys(role_ids))
    lineup: dict[Optional[int], int] = {}
    taken: set[int] = set()

    # 1) Закреплённые роли — всегда как указано, независимо от shuffle.
    unpinned: list[Optional[int]] = []
    for role_id in unique_roles:
        # list_primary_by_role отдаёт только явно закреплённых за ролью
        # (role_id == role_id, не резерв).
        pinned = link_repo.list_primary_by_role(campaign_id, role_id)
        available = [link for link in pinned if link.account_id not in taken]
        if available:
            chosen = rng.choice(available)
            lineup[role_id] = chosen.account_id
            taken.add(chosen.account_id)
        else:
            unpinned.append(role_id)

    if not unpinned:
        return lineup

    # 2) Остальные роли добираем из свободных аккаунтов кампании. При
    # shuffle=True состав мешается, иначе берём в стабильном порядке — тогда
    # раскладка повторяется от чата к чату.
    spare = [
        link
        for link in link_repo.list_by_campaign(campaign_id)
        if not link.is_reserve and link.account_id not in taken
    ]
    if shuffle:
        rng.shuffle(spare)
    for role_id in unpinned:
        if not spare:
            break
        chosen = spare.pop(0)
        lineup[role_id] = chosen.account_id
        taken.add(chosen.account_id)
    return lineup


# --- мониторинг каналов (cron) -----------------------------------------------

# Сколько новых постов максимум отрабатываем за один проход по одному каналу.
# Если канал за время между проходами выдал пачку постов, лезть в каждый —
# это всплеск активности сетки в одном месте, самый заметный паттерн.
_MONITOR_MAX_NEW_POSTS = 2


# Сколько каналов максимум заводим авто-дискавери за один проход по кампании —
# чтобы крупная подписка не превратилась в лавину resolve-запросов разом.
_MONITOR_ALL_MAX_CHANNELS = 50


async def _discover_account_channels(client) -> list[tuple[str, int]]:
    """Broadcast-каналы аккаунта из подписок → список (raw_input, channel_id).

    raw_input — @username (публичные) либо строковый id (приватные). Берём
    только каналы (broadcast), не группы: мониторим посты, а в группах постов
    в этом смысле нет. Приватные каналы без username мониторить можем —
    get_messages по id работает, пока аккаунт подписан."""
    out: list[tuple[str, int]] = []
    for dialog in await client.get_dialogs():
        entity = dialog.entity
        if not getattr(entity, "broadcast", False):
            continue
        cid = getattr(entity, "id", None)
        if cid is None:
            continue
        username = getattr(entity, "username", None)
        raw = f"@{username}" if username else str(int(cid))
        out.append((raw, int(cid)))
        if len(out) >= _MONITOR_ALL_MAX_CHANNELS:
            break
    return out


async def _reconcile_monitor_all(ctx, session_factory, pool, log) -> None:
    """Сверяет авто-цели с подписками аккаунта по тумблеру monitor_all_dialogs.

    Включён у кампании → заводим channel_monitor-цели на broadcast-каналы
    аккаунта-резолвера (auto_discovered=True), не трогая введённые руками и не
    плодя дубли. Выключен → удаляем авто-цели. Сам опрос постов делает основной
    цикл poll_channel_monitors — одинаково для ручных и авто-целей."""
    with session_factory() as session:
        plan: list[tuple[int, int]] = []  # (campaign_id, resolver_account_id)
        for campaign in CampaignRepository(session).list_active():
            target_repo = CampaignTargetRepository(session)
            if not campaign.monitor_all_dialogs:
                removed = target_repo.delete_auto_discovered(campaign.id)
                if removed:
                    session.commit()
                    log.info("shilling.monitor_all.cleanup", campaign_id=campaign.id, removed=removed)
                continue
            links = [
                link
                for link in CampaignAccountRepository(session).list_by_campaign(campaign.id)
                if not link.is_reserve
            ]
            if links:
                plan.append((campaign.id, links[0].account_id))

    for campaign_id, account_id in plan:
        try:
            client = await pool.get(account_id)
        except Exception as exc:  # noqa: BLE001
            log.info("shilling.monitor_all.client_failed", campaign_id=campaign_id, error=repr(exc))
            continue
        try:
            channels = await _discover_account_channels(client)
        except Exception as exc:  # noqa: BLE001 — подписки недоступны, пропускаем проход
            log.info("shilling.monitor_all.discover_failed", campaign_id=campaign_id, error=repr(exc))
            await pool.release(account_id)
            continue
        finally:
            await pool.release(account_id)

        added = 0
        with session_factory() as session:
            target_repo = CampaignTargetRepository(session)
            existing = target_repo.existing_raw_inputs(campaign_id)
            for raw, _cid in channels:
                if raw in existing:
                    continue
                target_repo.create(
                    campaign_id,
                    TargetCreate(raw_input=raw, mode="channel_monitor", auto_discovered=True),
                )
                existing.add(raw)
                added += 1
            if added:
                session.commit()
        if added:
            log.info("shilling.monitor_all.discovered", campaign_id=campaign_id, added=added)


async def poll_channel_monitors(ctx: dict) -> int:
    """Cron: ищет НОВЫЕ посты в каналах, добавленных в режиме «Мониторинг».

    Для каждой цели ``mode='channel_monitor'`` активной кампании смотрит посты
    свежее ``last_seen_post_id`` и ставит на каждый свой ``process_target`` с
    этим постом. При ПЕРВОМ проходе (курсора ещё нет) ничего не запускает —
    только запоминает текущий последний пост: иначе включение мониторинга
    означало бы заход в комментарии под всем архивом канала.

    Возвращает число запланированных диалогов.
    """
    now = _now(ctx)
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    pool = _pool(ctx)
    log = get_logger()

    # Тумблер «мониторить всё, что на аккаунте»: до основного цикла сверяем
    # авто-цели с подписками аккаунта (у кого включено) и чистим их (у кого
    # выключено). Дальше цикл опрашивает ВСЕ channel_monitor-цели — и ручные,
    # и авто — одинаково.
    await _reconcile_monitor_all(ctx, session_factory, pool, log)

    with session_factory() as session:
        campaigns = CampaignRepository(session).list_active()
        jobs: list[tuple[int, int, str, Optional[int], Optional[int]]] = []
        for campaign in campaigns:
            targets = CampaignTargetRepository(session).list_monitors(campaign.id)
            if not targets:
                continue
            links = [
                link
                for link in CampaignAccountRepository(session).list_by_campaign(campaign.id)
                if not link.is_reserve
            ]
            if not links:
                continue
            resolver_account_id = links[0].account_id
            for target in targets:
                jobs.append(
                    (
                        campaign.id,
                        target.id,
                        target.raw_input,
                        target.last_seen_post_id,
                        resolver_account_id,
                    )
                )

    if not jobs:
        return 0

    scheduled = 0
    for campaign_id, target_id, raw_input, last_seen, resolver_account_id in jobs:
        try:
            client = await pool.get(resolver_account_id)
        except Exception as exc:  # noqa: BLE001 — аккаунт недоступен, не падаем
            log.info("shilling.monitor.client_failed", target_id=target_id, error=repr(exc))
            continue
        try:
            posts = await client.get_messages(raw_input, limit=_MONITOR_MAX_NEW_POSTS + 1)
        except Exception as exc:  # noqa: BLE001 — канал недоступен/переименован
            log.info("shilling.monitor.fetch_failed", target_id=target_id, error=repr(exc))
            await pool.release(resolver_account_id)
            continue
        finally:
            await pool.release(resolver_account_id)

        post_ids = [p.id for p in posts if getattr(p, "id", None) is not None]
        if not post_ids:
            continue
        newest = max(post_ids)

        if last_seen is None:
            # Первый проход — только ставим курсор, в архив не лезем.
            with session_factory() as session:
                CampaignTargetRepository(session).set_last_seen_post(target_id, newest)
                session.commit()
            log.info("shilling.monitor.cursor_init", target_id=target_id, post_id=newest)
            continue

        fresh = sorted(p for p in post_ids if p > last_seen)[:_MONITOR_MAX_NEW_POSTS]
        if not fresh:
            continue
        for new_post_id in fresh:
            await task_queue.enqueue(
                TaskName.SHILLING_PROCESS_TARGET, campaign_id, target_id, new_post_id
            )
            scheduled += 1
        with session_factory() as session:
            CampaignTargetRepository(session).set_last_seen_post(target_id, max(fresh))
            session.commit()
        log.info(
            "shilling.monitor.new_posts",
            target_id=target_id, posts=len(fresh), newest=max(fresh),
        )

    if scheduled:
        log.info("shilling.monitor.scheduled", dialogs=scheduled, now=now.isoformat())
    return scheduled


# --- задача failover ---------------------------------------------------------


async def failover(
    ctx: dict,
    campaign_id: int,
    target_id: int,
    step_id: int,
    failed_account_id: int,
    thread_msg_id: Optional[int] = None,
) -> Optional[int]:
    """Заменяет забаненный аккаунт резервным той же роли и продолжает шаг.

    Возвращает id нового аккаунта, если замена произошла, иначе None.
    Если резерв исчерпан (или выключен) — цель уходит в ЧС (auto=True).
    """
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None or not campaign.enabled or campaign.status != "running":
            log.info("shilling.failover.skip", campaign_id=campaign_id, reason="not_running")
            return None

        link_repo = CampaignAccountRepository(session)
        failed_link = link_repo.get_link(campaign_id, failed_account_id)
        role_id = failed_link.role_id if failed_link else None

        # Реролл запрещён без включённого резерва → сразу в ЧС.
        if not campaign.reserve_enabled:
            _blacklist_target(session, campaign_id, target_id, reason="reserve disabled")
            session.commit()
            log.warning("shilling.failover.reserve_disabled", campaign_id=campaign_id)
            return None

        # Аккаунты, уже провалившиеся на этой цели — не пробуем повторно.
        failed_ids = {
            entry.account_id
            for entry in ExecutionLogRepository(session).list_failed_for_target(
                campaign_id, target_id
            )
        }
        failed_ids.add(failed_account_id)

        acc_repo = AccountRepository(session)
        chosen = None
        for reserve in link_repo.list_reserve(campaign_id):
            if reserve.account_id in failed_ids:
                continue
            # Резерв без роли (None) можно поставить на любую; иначе роль должна
            # совпадать с ролью выбывшего аккаунта.
            if reserve.role_id not in (None, role_id):
                continue
            acc = acc_repo.get(reserve.account_id)
            if acc is None or acc.status not in _USABLE_ACCOUNT_STATUSES:
                continue
            chosen = reserve
            break

        if chosen is None:
            _blacklist_target(session, campaign_id, target_id, reason="reserve exhausted")
            session.commit()
            log.warning(
                "shilling.failover.reserve_exhausted",
                campaign_id=campaign_id, target_id=target_id,
            )
            return None

        # Повышаем резерв в основной состав на роль выбывшего, выбывшего снимаем.
        chosen.is_reserve = False
        chosen.role_id = role_id
        link_repo.detach(campaign_id, failed_account_id)
        # Логируем сам факт замены: UI в истории покажет replaced-строку,
        # чтобы по статистике кампании было видно, где и почему был failover.
        # Если шаг пропал (например, сценарий пересобрали пока задача висела),
        # пишем step_id=None — FK scenario_steps nullable + SET NULL в модели.
        step_still_exists = ScenarioStepRepository(session).get(step_id) is not None
        ExecutionLogRepository(session).create(
            ExecutionLogCreate(
                campaign_id=campaign_id,
                target_id=target_id,
                account_id=failed_account_id,
                role_id=role_id,
                step_id=step_id if step_still_exists else None,
                message_text=None,
                posted_message_id=None,
                status="replaced",
                error=f"replaced_by:{chosen.account_id}",
            )
        )
        session.commit()
        new_account_id = chosen.account_id

    await task_queue.enqueue(
        TaskName.SHILLING_EXECUTE_STEP,
        campaign_id,
        target_id,
        step_id,
        new_account_id,
        thread_msg_id=thread_msg_id,
    )
    log.info(
        "shilling.failover.replaced",
        campaign_id=campaign_id,
        failed_account_id=failed_account_id,
        new_account_id=new_account_id,
        role_id=role_id,
    )
    return new_account_id


def _blacklist_target(session, campaign_id: int, target_id: int, *, reason: str) -> None:
    """Добавляет цель в ЧС кампании (auto=True). Идемпотентно."""
    target = CampaignTargetRepository(session).get(target_id)
    if target is None:
        return
    bl_repo = BlacklistRepository(session)
    chat_id = target.resolved_chat_id
    username = target.raw_input if target.kind == "username" else None
    if chat_id is None and not username:
        return  # нечего заносить (BlacklistCreate требует идентификатор)
    if bl_repo.is_blacklisted(campaign_id, chat_id=chat_id, username=username):
        return
    bl_repo.create(
        campaign_id,
        BlacklistCreate(chat_id=chat_id, username=username, reason=reason),
        auto=True,
    )
