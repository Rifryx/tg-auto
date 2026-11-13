"""Раннер модуля commenting: on_new_post и post_comment (PROJECT-STAGES §5, §8.3).

Порядок: новый пост → on_new_post выбирает N аккаунтов, генерирует комментарии
(LLM + StyleRandomizer) и планирует их постинг с задержками → post_comment
резервирует слот governor, шлёт реплай через ClientPool (обёрнуто в
around_telethon_call) и пишет CommentLog. После успешного коммента с шансом
CONTINUE — второй раунд треда (ответ на свой же коммент), глубина ≤ MAX_DEPTH.

Инъекции через ctx (для тестов): now, rng, client_pool, task_queue, governor,
llm_provider, publisher.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from core.enums import CommentStatus
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.repositories.persona import PersonaRepository
from modules.commenting.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CommentLogRepository,
    MonitoredChannelRepository,
)
from modules.commenting.schemas import CommentLogCreate
import structlog

from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatGuestSendForbiddenError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    UserNotParticipantError,
)

from modules.commenting.worker import delivery, limits
from modules.commenting.worker.alerts import auto_blacklist, raise_alert
from modules.commenting.worker.captcha import maybe_solve_captcha
from modules.commenting.worker.timeline import TimelineKind


_SKIP_LABELS = {
    "max_comments_reached": "достигнут лимит комментариев кампании",
    "daily_limit_reached": "достигнут дневной лимит аккаунта",
    "outside_post_window": "пост старше окна «комментировать после публикации»",
    "paused": "пауза между комментариями",
    "scheduled_not_started": "ещё не наступило время отложенного запуска",
}


def _skip_label(reason: str) -> str:
    return _SKIP_LABELS.get(reason, reason)
from worker.client_pool import ClientPool
from worker.health import Governor, around_telethon_call
from worker.llm import Message, StyleRandomizer, get_provider, with_direct_output

get_logger = structlog.get_logger

# --- параметры (§5) ----------------------------------------------------------
MIN_ACCOUNTS_PER_POST = 2
MAX_ACCOUNTS_PER_POST = 4
THREAD_CONTINUE_PROB = 0.35
MAX_THREAD_DEPTH = 3
GOVERNOR_RETRY_MINUTES = 5
# Потолок ожидания отправки коммента: дольше — считаем зависанием (прокси/сеть)
# и фиксируем как ошибку, а не держим задачу в «вечной загрузке».
_DELIVER_TIMEOUT_SEC = 90
# Потолок на генерацию ответа LLM (с учётом до 3 попыток min_words): если
# провайдер недоступен/завис — «Генерирую…» не висит вечно, пишем ошибку.
_GENERATE_TIMEOUT_SEC = 120


# --- ctx-инъекции ------------------------------------------------------------


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _fmt_local(dt: datetime, campaign) -> str:
    """Время для сообщений в таймлайне — в часовом поясе КАМПАНИИ, не сервера.

    Баг-фикс: раньше ``dt.astimezone()`` (без аргумента) брал системный tz
    процесса воркера (обычно UTC в контейнере) — время в сообщении («опубликую
    через 31с (~18:15:34)») не совпадало с временем самого события в ленте
    («20:15:05», отрендеренным фронтом в tz браузера пользователя). Кампания
    уже хранит ``active_hours_tz`` (часовой пояс, который пользователь сам
    выбрал для расписания) — логично показывать ETA в нём же.
    """
    try:
        tz = ZoneInfo(campaign.active_hours_tz) if campaign is not None else None
    except Exception:  # noqa: BLE001 — некорректная/неизвестная tz в БД
        tz = None
    return dt.astimezone(tz).strftime("%H:%M:%S")


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _governor(ctx: dict) -> Governor:
    return ctx.get("governor") or Governor(ctx.get("redis"))


def _style(ctx: dict) -> StyleRandomizer:
    return ctx.get("style_randomizer") or StyleRandomizer(_rng(ctx))


def _claim_once(ctx: dict, key: str, ttl: int = 3600) -> bool:
    """Идемпотентный claim через redis SETNX: True — первый раз, False — дубль.

    Защита от двойного коммента на один пост: при переподключении слушателя или
    двойном срабатывании handler'а тот же пост может прийти дважды за секунды.
    Без claim это даёт два одинаковых коммента. redis_sync — синхронный клиент
    (как в registry). Нет redis (тесты) или ошибка → fail-open (не блокируем)."""
    r = ctx.get("redis_sync")
    if r is None:
        return True
    try:
        return bool(r.set(key, "1", nx=True, ex=ttl))
    except Exception:  # noqa: BLE001 — лучше коммент, чем молчание
        return True


def _push(ctx: dict, campaign_id: Optional[int], kind, message: str, meta: Optional[dict] = None) -> None:
    """Событие в live-таймлайн кампании (этап публикации коммента был «слепым»).

    Берём СИНХРОННЫЙ redis (ctx['redis_sync']) — как в registry; с async arq-
    клиентом push_event молча ничего не пишет. В тестах ключа нет → no-op."""
    if campaign_id is None:
        return
    from modules.commenting.worker.timeline import push_event

    push_event(ctx.get("redis_sync"), campaign_id, kind, message, meta or {})


# --- helpers -----------------------------------------------------------------


def is_within_active_hours(now: datetime, campaign) -> bool:
    try:
        tz = ZoneInfo(campaign.active_hours_tz)
    except Exception:  # pragma: no cover
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz).timetz().replace(tzinfo=None)
    start, end = campaign.active_hours_start, campaign.active_hours_end
    if start <= end:
        return start <= local <= end
    return local >= start or local <= end


def _scheduled_not_yet(campaign, now: datetime) -> bool:
    """Отложенный запуск: True — время scheduled_start_at ещё не наступило."""
    at = getattr(campaign, "scheduled_start_at", None)
    if at is None:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return now < at


def _assigned_accounts(session, campaign_id: int) -> list:
    links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
    accounts_repo = AccountRepository(session)
    result = []
    for link in links:
        account = accounts_repo.get(link.account_id)
        if account is not None and account.status == "assigned":
            result.append(account)
    return result


def _product_mention_suffix(campaign, rng: Optional[random.Random]) -> str:
    """С вероятностью product_mention_chance_percent просим LLM органично
    упомянуть продукт/бренд кампании (+ ссылку, если задана). Без тумблера
    или без имени продукта — пусто (поведение не меняется)."""
    if not getattr(campaign, "product_mention_enabled", False):
        return ""
    name = (getattr(campaign, "product_name", None) or "").strip()
    if not name:
        return ""
    chance = max(0, min(100, int(getattr(campaign, "product_mention_chance_percent", 0) or 0)))
    r = rng or random.Random()
    if r.randint(1, 100) > chance:
        return ""
    url = (getattr(campaign, "product_url", None) or "").strip()
    line = f"\n\nЕстественно и ненавязчиво упомяни в комментарии «{name}»"
    if url:
        line += f" (ссылка: {url})"
    line += ". Это должно звучать органично, как личная рекомендация, а не реклама."
    return line


def _build_system_prompt(session, campaign, account, *, rng: Optional[random.Random] = None) -> str:
    override = CampaignAccountRepository(session).get(campaign.id, account.id)
    prompt = (override.override_prompt if override and override.override_prompt else None)
    prompt = prompt or campaign.base_system_prompt
    # Персона аккаунта перекрывает персону кампании; кампания — дефолт для тех,
    # у кого своей нет.
    persona_id = account.persona_id or getattr(campaign, "persona_id", None)
    if persona_id is not None:
        persona = PersonaRepository(session).get(persona_id)
        if persona is not None:
            tags = ", ".join(persona.personality_tags or [])
            prompt = f"{prompt}\n\nТы — {persona.name}. Черты: {tags}."
    # Сервисное правило: выдавать СРАЗУ готовый коммент, а не «вот варианты».
    # Добавляем поверх пользовательского промпта кампании — он может быть
    # свободным, но формат вывода всё равно обязан быть один готовый текст.
    prompt = with_direct_output(prompt)
    # use_emojis=False: явно просим LLM не использовать эмодзи; ниже в
    # _generate ещё раз почистим safety net'ом (E4.1).
    prompt += delivery.emoji_prompt_suffix(campaign)
    # Потолок длины: просим уложиться, а в _generate ещё и обрежем safety-net'ом.
    max_words = getattr(campaign, "max_words", None)
    if max_words:
        prompt += f"\n\nКоммент должен быть коротким — не длиннее {max_words} слов."
    prompt += _product_mention_suffix(campaign, rng)
    return prompt


# Сколько символов текста поста отдаём модели как контекст (длинные посты режем).
_POST_CONTEXT_LIMIT = 2000


def _thread_context(
    session, campaign_id: int, channel_msg_id: int, post_text: Optional[str] = None
) -> list[Message]:
    logs = CommentLogRepository(session).list_by_campaign(campaign_id, limit=100)
    thread = [
        log for log in logs
        if log.post_channel_msg_id == channel_msg_id and log.status == CommentStatus.POSTED.value
    ]
    thread.sort(key=lambda log: log.id)
    # Главное: даём модели ТЕКСТ поста, а не его номер. Иначе ей не на что
    # отвечать — и она сползает в ассистентский «вот несколько вариантов».
    body = (post_text or "").strip()
    if body:
        head = (
            "Вот пост в канале. Напиши к нему один живой комментарий от своего "
            f"лица:\n\n{body[:_POST_CONTEXT_LIMIT]}"
        )
    else:
        head = (
            "Пост в канале без текста (фото/видео/вложение). Напиши один короткий "
            "уместный комментарий по теме канала от своего лица."
        )
    messages = [Message(role="user", content=head)]
    messages += [Message(role="assistant", content=log.comment_text) for log in thread]
    # Разговор ДОЛЖЕН заканчиваться на user: это тред-продолжение (аккаунт
    # отвечает сам себе), и без финального user-сообщения список заканчивается
    # на assistant — многие шлюзы (в т.ч. AnyModel/Gemini) такое отклоняют с
    # 400 Bad Request. Баг проявлялся именно на второй-и-далее генерации в
    # треде: «Ошибка генерации ответа: HTTPStatusError 400» сразу после
    # успешной публикации первого коммента.
    if messages[-1].role == "assistant":
        messages.append(
            Message(
                role="user",
                content="Продолжи мысль одной короткой репликой — как будто дополняешь свой же комментарий.",
            )
        )
    return messages


def _persona_for(session, account):
    if account.persona_id is None:
        return None
    return PersonaRepository(session).get(account.persona_id)


def _blacklisted(session, campaign_id: int, *, chat_id: Optional[int], ref: Optional[str]) -> bool:
    """Канал в чёрном списке кампании (по id канала или username без «@»)."""
    from modules.commenting.repositories import ChannelBlacklistRepository

    username = (ref or "").lstrip("@") or None
    return (
        ChannelBlacklistRepository(session).find(campaign_id, chat_id=chat_id, username=username)
        is not None
    )


# Ошибки доступа при отправке (E3.2). Не роняем задачу (иначе воркер
# повторит отправку впустую), а разбираем: лог + алерт + действие.
_NO_ACCESS = (ChannelPrivateError, ChannelInvalidError)
_NOT_MEMBER = (UserNotParticipantError, ChatGuestSendForbiddenError)
_NO_RIGHTS = (ChatWriteForbiddenError, UserBannedInChannelError, ChatAdminRequiredError)
ACCESS_ERRORS = _NO_ACCESS + _NOT_MEMBER + _NO_RIGHTS


async def _schedule_verify(ctx: dict, campaign_id: int, comment_log_id: Optional[int], posted_message_id: Optional[int], now: datetime) -> None:
    if comment_log_id is None or posted_message_id is None:
        return
    with ctx["session_factory"]() as session:
        campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None or not campaign.verify_after_post:
        return
    run_at = now + timedelta(seconds=campaign.verify_delay_sec)
    await _task_queue(ctx).schedule(
        TaskName.COMMENTING_VERIFY_COMMENT, run_at, comment_log_id
    )


async def _maybe_solve_captcha(ctx, client, account_id: int, discussion_group_id: int, campaign, now: datetime) -> None:
    """Best-effort капча-солвер перед отправкой коммента (см. worker/captcha.py).

    Никогда не бросает и не блокирует обычный комментинг надолго — своя
    логика внутри уже best-effort/с таймаутами на уровне Telethon-вызовов."""
    if discussion_group_id is None:
        return
    try:
        provider = ctx.get("llm_provider") or get_provider(campaign.llm_provider)
        await maybe_solve_captcha(
            ctx, client,
            account_id=account_id,
            discussion_group_id=discussion_group_id,
            provider=provider,
            publisher=ctx.get("publisher"),
            now=now,
        )
    except Exception as exc:  # noqa: BLE001 — капча вспомогательная, не роняем коммент
        get_logger().info("commenting.captcha.unexpected_error", account_id=account_id, error=repr(exc))


def _postbot_failure_log(session_factory, campaign_id: int, account_id: int, channel_msg_id: int, reply_to: int, exc: Exception) -> None:
    with session_factory() as session:
        CommentLogRepository(session).create(
            CommentLogCreate(
                campaign_id=campaign_id,
                account_id=account_id,
                post_channel_msg_id=channel_msg_id,
                comment_text="[Postbot]",
                status=CommentStatus.FAILED,
                in_reply_to_message_id=reply_to,
                error=f"postbot_failed:{type(exc).__name__}: {exc}"[:500],
            )
        )
        session.commit()


async def _handle_access_error(
    ctx: dict,
    exc: Exception,
    *,
    campaign_id: int,
    account_id: int,
    channel_msg_id: int,
    text: str,
    reply_to: int,
    channel_ref: Optional[str],
    channel_tg_id: Optional[int],
    monitored_channel_id: Optional[int],
    blacklist_username: Optional[str] = None,
) -> None:
    """channel_ref — ключ алертов (исходная ссылка, как у резолвера, чтобы он
    сам закрыл алерт после переподписки); blacklist_username — username канала
    для ЧС."""
    from modules.commenting.worker.channels import ACTION_DETACH, publish_channel_lifecycle

    publisher = ctx.get("publisher")
    err = type(exc).__name__
    ref = channel_ref or (f"tg:{channel_tg_id}" if channel_tg_id else "?")
    rejoin = False
    detach = False

    with ctx["session_factory"]() as session:
        CommentLogRepository(session).create(
            CommentLogCreate(
                campaign_id=campaign_id, account_id=account_id,
                post_channel_msg_id=channel_msg_id, comment_text=text,
                status=CommentStatus.FAILED, in_reply_to_message_id=reply_to,
                error=f"access:{err}",
            )
        )
        session.commit()
        mon_repo = MonitoredChannelRepository(session)

        if isinstance(exc, _NO_ACCESS):
            # Канал закрыт/недоступен — в ЧС кампании, чтобы не пытаться снова.
            username = (blacklist_username or channel_ref or "").lstrip("@") or None
            if username and username.startswith("tg:"):
                username = None
            added = (channel_tg_id is not None or username is not None) and auto_blacklist(
                session, campaign_id=campaign_id, chat_id=channel_tg_id,
                username=username, reason=err,
            )
            if added:
                raise_alert(
                    session, publisher, campaign_id=campaign_id, account_id=account_id,
                    channel_ref=ref, kind="blacklisted",
                    detail=f"Канал недоступен ({err}) — добавлен в чёрный список кампании.",
                )
            detach = True
        elif isinstance(exc, _NOT_MEMBER):
            campaign = CampaignRepository(session).get(campaign_id)
            subscribe = campaign is not None and campaign.on_not_subscribed_action == "subscribe_and_notify"
            raise_alert(
                session, publisher, campaign_id=campaign_id, account_id=account_id,
                channel_ref=ref, kind="not_subscribed",
                detail=(
                    "Аккаунт не состоит в канале/обсуждении — подписываем заново."
                    if subscribe and monitored_channel_id
                    else "Аккаунт не состоит в канале/обсуждении — коммент не отправлен."
                ),
            )
            rejoin = bool(subscribe and monitored_channel_id)
            detach = not rejoin
        else:
            raise_alert(
                session, publisher, campaign_id=campaign_id, account_id=account_id,
                channel_ref=ref, kind="access_lost",
                detail=f"Нет прав писать в обсуждение ({err}).",
            )
            detach = True

        if monitored_channel_id is not None:
            if rejoin:
                row = mon_repo.get(monitored_channel_id)
                if row is not None:
                    row.status = "pending"
                    row.error = None
            else:
                mon_repo.mark_failed(monitored_channel_id, f"access:{err}")
            session.commit()

    if monitored_channel_id is not None:
        if rejoin:
            await _task_queue(ctx).enqueue(TaskName.COMMENTING_RESOLVE_CHANNEL, monitored_channel_id)
        if detach or rejoin:
            publish_channel_lifecycle(publisher, account_id, monitored_channel_id, ACTION_DETACH)
    get_logger().warning(
        "commenting.post.access_error", account_id=account_id, campaign_id=campaign_id,
        error=err, rejoin=rejoin,
    )


def _limit_skip_reason(session, campaign, post_date_ts: Optional[float], now: datetime) -> Optional[str]:
    """Причина не комментировать по лимитам кампании (E2.2) или None."""
    if limits.max_comments_reached(session, campaign):
        return "max_comments_reached"
    if limits.window_closed(campaign, limits.post_date_from_ts(post_date_ts), now):
        return "window_closed"
    return None


def _fallback_provider(ctx, primary_name: str):
    """Другой LLM-провайдер, если для него есть рабочий путь — страховка на
    случай, когда у выбранного провайдера ключ пустой/битый/недоступен
    (401, таймаут, квота). Модель больше не выбирает пользователь (убрано из
    UI) — это единственный способ «переключиться» при сбое, см.
    worker/llm/factory.py::fallback_provider. В тестах с инъекцией
    ``ctx['llm_provider']`` фолбэк отключаем."""
    if ctx.get("llm_provider") is not None:
        return None
    from worker.llm import fallback_provider

    return fallback_provider(primary_name)


async def _generate(ctx, session, campaign, account, provider, context) -> tuple[str, bool]:
    """Текст коммента с учётом min_words (до 3 попыток) и стиля (E4.1)."""
    system = _build_system_prompt(session, campaign, account, rng=_rng(ctx))
    persona = _persona_for(session, account)
    style = _style(ctx)
    fallback = _fallback_provider(ctx, campaign.llm_provider)

    async def once() -> str:
        try:
            raw = await provider.generate(system, context)
        except Exception as exc:  # noqa: BLE001 — пробуем второй провайдер
            if fallback is None:
                raise
            get_logger().warning(
                "commenting.generate.primary_failed_fallback",
                provider=campaign.llm_provider, error=repr(exc),
            )
            raw = await fallback.generate(system, context)
        return delivery.apply_style(raw, campaign, persona, style)

    return await limits.generate_with_min_words(once, campaign.min_words or 0)


def _skip_llm_mode(campaign) -> str:
    """'postbot' | 'economy' | 'normal' — какой режим доставки для кампании.

    Postbot важнее economy: если включены оба, LLM и так не нужен ни в одном
    из них, и postbot — более явный, явно заданный пользователем пул постов."""
    if getattr(campaign, "postbot_forward_enabled", False) and getattr(campaign, "postbot_message_ids", None):
        return "postbot"
    if getattr(campaign, "token_economy_enabled", False):
        return "economy"
    return "normal"


def _log_below_min_words(session, campaign, account_id, channel_msg_id, text, reply_to) -> None:
    """Не набрали min_words — коммент не шлём, но фиксируем в логе/статистике."""
    CommentLogRepository(session).create(
        CommentLogCreate(
            campaign_id=campaign.id,
            account_id=account_id,
            post_channel_msg_id=channel_msg_id,
            comment_text=text,
            status=CommentStatus.FAILED,
            in_reply_to_message_id=reply_to,
            error=f"below_min_words:{campaign.min_words}",
        )
    )
    session.commit()


# --- задача on_new_post ------------------------------------------------------


async def on_new_post(
    ctx: dict,
    campaign_id: int,
    channel_msg_id: int,
    in_reply_to: Optional[int] = None,
    thread_depth: int = 0,
    post_date_ts: Optional[float] = None,
    post_text: Optional[str] = None,
) -> int:
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None or not campaign.enabled:
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason="disabled")
            return 0
        if _scheduled_not_yet(campaign, now):
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason="scheduled_not_started")
            return 0
        if not is_within_active_hours(now, campaign):
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason="inactive_hours")
            return 0
        reason = _limit_skip_reason(session, campaign, post_date_ts, now)
        if reason:
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason=reason)
            return 0
        if _blacklisted(session, campaign_id, chat_id=None, ref=campaign.target_channel):
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason="blacklisted")
            return 0

        accounts = _assigned_accounts(session, campaign_id)
        if not accounts:
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason="no_accounts")
            return 0

        n_hi = min(MAX_ACCOUNTS_PER_POST, len(accounts))
        n_lo = min(MIN_ACCOUNTS_PER_POST, len(accounts))
        chosen = rng.sample(accounts, rng.randint(n_lo, n_hi))

        reply_target = in_reply_to if in_reply_to is not None else channel_msg_id
        provider = ctx.get("llm_provider") or get_provider(campaign.llm_provider)
        delay_lo = campaign.posting_delay_min_sec
        delay_hi = campaign.posting_delay_max_sec
        # postbot/economy: LLM не зовём ЗДЕСЬ вообще — postbot тексту не
        # нужен, economy откладывает ИИ-вызов до прохождения стаб-пробника
        # (post_comment). Так реально экономим токены, а не только на словах.
        mode = _skip_llm_mode(campaign)

        plans = []
        for account in chosen:
            if mode != "normal":
                text, ok = "", True
            else:
                context = _thread_context(session, campaign_id, channel_msg_id, post_text)
                text, ok = await _generate(ctx, session, campaign, account, provider, context)
                if not ok:
                    _log_below_min_words(session, campaign, account.id, channel_msg_id, text, reply_target)
                    log.info("commenting.on_new_post.skip_account", account_id=account.id, reason="below_min_words")
                    continue
            delay = rng.uniform(delay_lo, delay_hi)
            plans.append((account.id, text, delay))

    for account_id, text, delay in plans:
        run_at = now + timedelta(seconds=delay)
        await task_queue.schedule(
            TaskName.COMMENTING_POST_COMMENT,
            run_at,
            campaign_id,
            account_id,
            text,
            channel_msg_id,
            reply_target,
            thread_depth=thread_depth,
            post_date_ts=post_date_ts,
            post_text=post_text if mode == "economy" else None,
            economy_stub=mode == "economy",
            postbot_forward=mode == "postbot",
        )
    log.info(
        "commenting.on_new_post.scheduled",
        campaign_id=campaign_id,
        channel_msg_id=channel_msg_id,
        count=len(plans),
        thread_depth=thread_depth,
    )
    return len(plans)


# --- задача post_comment -----------------------------------------------------


async def post_comment(
    ctx: dict,
    campaign_id: int,
    account_id: int,
    text: str,
    channel_msg_id: int,
    in_reply_to_message_id: int,
    thread_depth: int = 0,
    post_date_ts: Optional[float] = None,
    post_text: Optional[str] = None,
    economy_stub: bool = False,
    postbot_forward: bool = False,
) -> Optional[int]:
    now = _now(ctx)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    task_queue = _task_queue(ctx)
    log = get_logger()

    async def reschedule(run_at: datetime) -> None:
        await task_queue.schedule(
            TaskName.COMMENTING_POST_COMMENT,
            run_at,
            campaign_id,
            account_id,
            text,
            channel_msg_id,
            in_reply_to_message_id,
            thread_depth=thread_depth,
            post_date_ts=post_date_ts,
            post_text=post_text,
            economy_stub=economy_stub,
            postbot_forward=postbot_forward,
        )

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None:
            log.info("commenting.post_comment.skip", account_id=account_id, reason="no_campaign")
            return None
        if not is_within_active_hours(now, campaign):
            log.info("commenting.post_comment.skip", account_id=account_id, reason="inactive_hours")
            return None
        # Лимиты перепроверяем при отправке: между планированием и отправкой
        # мог набраться max_comments или закрыться окно.
        reason = _limit_skip_reason(session, campaign, post_date_ts, now)
        if reason:
            log.info("commenting.post_comment.skip", account_id=account_id, reason=reason)
            return None
        wait = limits.pause_wait_until(
            CampaignAccountRepository(session).get(campaign_id, account_id), campaign, now
        )
        discussion_group_id = campaign.discussion_group_id
        target_channel = campaign.target_channel

    if wait is not None:
        await reschedule(wait)
        log.info("commenting.post_comment.paused", account_id=account_id, until=wait.isoformat())
        return None

    # rate-limit governor
    if not await _governor(ctx).check_and_reserve(account_id, "comment"):
        await reschedule(now + timedelta(minutes=GOVERNOR_RETRY_MINUTES))
        log.info("commenting.post_comment.rate_limited", account_id=account_id)
        return None

    # Занимаем слот паузы атомарно (FOR UPDATE): гонка двух задач аккаунта.
    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        wait = limits.claim_post_slot(session, campaign, account_id, now)
    if wait is not None:
        await reschedule(wait)
        log.info("commenting.post_comment.paused", account_id=account_id, until=wait.isoformat())
        return None

    # Кампания нужна для delivery.deliver_comment: use_stickers / attach_image /
    # write_as_channel читаются оттуда. Берём свежую (могли поменять флаги за
    # время между планированием и отправкой).
    with session_factory() as session:
        campaign_row = CampaignRepository(session).get(campaign_id)

    async def _generate_real() -> str:
        """Полноценная ИИ-генерация на месте — используется economy-пробником
        и как safety net, если text пуст (кампания сменила режим между
        планированием on_new_post и отправкой: флаг economy/postbot успели
        выключить, а запланированный текст был пуст — лучше сгенерировать,
        чем отправить пустое сообщение)."""
        with session_factory() as gen_session:
            gen_campaign = CampaignRepository(gen_session).get(campaign_id)
            gen_account = AccountRepository(gen_session).get(account_id)
            gen_provider = ctx.get("llm_provider") or get_provider(gen_campaign.llm_provider)
            gen_context = _thread_context(gen_session, campaign_id, channel_msg_id, post_text)
            gen_text, ok = await _generate(ctx, gen_session, gen_campaign, gen_account, gen_provider, gen_context)
            return gen_text if ok else delivery.stub_text(_rng(ctx))

    pool = _pool(ctx)
    client = await pool.get(account_id)
    try:
        if campaign_row.captcha_solving_enabled:
            await _maybe_solve_captcha(ctx, client, account_id, discussion_group_id, campaign_row, now)
        final_text = text
        is_economy = False
        if postbot_forward and campaign_row.postbot_forward_enabled and campaign_row.postbot_message_ids:
            try:
                sent, delivery_mode, picked_id = await delivery.deliver_postbot(
                    ctx, client, campaign_row,
                    account_id=account_id,
                    discussion_group_id=discussion_group_id,
                    reply_to=in_reply_to_message_id,
                    now=now,
                    publisher=publisher,
                    rng=_rng(ctx),
                )
            except ACCESS_ERRORS as exc:
                await _handle_access_error(
                    ctx, exc, campaign_id=campaign_id, account_id=account_id,
                    channel_msg_id=channel_msg_id, text=text, reply_to=in_reply_to_message_id,
                    channel_ref=target_channel, channel_tg_id=None, monitored_channel_id=None,
                )
                return None
            except Exception as exc:  # noqa: BLE001 — бот/пост Postbot недоступен
                log.warning("commenting.post_comment.postbot_failed", account_id=account_id, error=repr(exc))
                _postbot_failure_log(session_factory, campaign_id, account_id, channel_msg_id, in_reply_to_message_id, exc)
                return None
            final_text = f"[Postbot #{picked_id}]"
        elif economy_stub and campaign_row.token_economy_enabled:
            sent, delivery_mode, final_text = await delivery.deliver_economy(
                ctx, client, campaign_row,
                account_id=account_id,
                discussion_group_id=discussion_group_id,
                reply_to=in_reply_to_message_id,
                now=now,
                publisher=publisher,
                rng=_rng(ctx),
                generate_real=_generate_real,
            )
            is_economy = True
            if delivery_mode == "economy_failed":
                with session_factory() as session:
                    CommentLogRepository(session).create(
                        CommentLogCreate(
                            campaign_id=campaign_id,
                            account_id=account_id,
                            post_channel_msg_id=channel_msg_id,
                            comment_text=final_text,
                            status=CommentStatus.FAILED,
                            in_reply_to_message_id=in_reply_to_message_id,
                            error="economy_probe_failed",
                            is_economy_stub=True,
                        )
                    )
                    session.commit()
                log.info("commenting.post_comment.economy_probe_failed", account_id=account_id)
                _push(
                    ctx, campaign_id, TimelineKind.COMMENT_FAILED,
                    f"Экономия токенов (акк. #{account_id}): заглушка не прошла "
                    "(удалена ботом/модератором) — ИИ не вызывался, токены сэкономлены.",
                    {"account_id": account_id, "reason": "economy_probe_failed"},
                )
                return None
        else:
            # Safety net: text пуст, если scheduling был под economy/postbot,
            # но кампания успела сменить режим до отправки — генерируем, а не
            # шлём пустое сообщение.
            if not text:
                text = await _generate_real()
                final_text = text
            sent, delivery_mode = await delivery.deliver_comment(
                ctx, client, campaign_row,
                account_id=account_id,
                discussion_group_id=discussion_group_id,
                text=text,
                reply_to=in_reply_to_message_id,
                now=now,
                publisher=publisher,
                rng=_rng(ctx),
            )
    except ACCESS_ERRORS as exc:
        await _handle_access_error(
            ctx, exc, campaign_id=campaign_id, account_id=account_id,
            channel_msg_id=channel_msg_id, text=text, reply_to=in_reply_to_message_id,
            channel_ref=target_channel, channel_tg_id=None, monitored_channel_id=None,
        )
        return None
    finally:
        await pool.release(account_id)

    posted_message_id = getattr(sent, "id", None)
    comment_log_id = None
    with session_factory() as session:
        row = CommentLogRepository(session).create(
            CommentLogCreate(
                campaign_id=campaign_id,
                account_id=account_id,
                post_channel_msg_id=channel_msg_id,
                comment_text=final_text,
                status=CommentStatus.POSTED,
                posted_message_id=posted_message_id,
                in_reply_to_message_id=in_reply_to_message_id,
                is_economy_stub=is_economy,
                channel_ref=target_channel,
            )
        )
        session.commit()
        comment_log_id = row.id
    # Verify-after-post (E4.2): расписываем задачу тем же аккаунтом на now +
    # verify_delay_sec. Кампанию берём свежую — verify_after_post могли
    # включить/выключить между планированием и отправкой коммента.
    await _schedule_verify(ctx, campaign_id, comment_log_id, posted_message_id, now)

    log.info(
        "commenting.post_comment.posted",
        account_id=account_id,
        posted_message_id=posted_message_id,
        thread_depth=thread_depth,
    )
    await maybe_continue_thread(
        ctx, campaign_id, channel_msg_id, posted_message_id, thread_depth, post_date_ts,
        campaign=campaign_row,
    )
    return posted_message_id


async def maybe_continue_thread(
    ctx: dict,
    campaign_id: int,
    channel_msg_id: int,
    comment_msg_id: Optional[int],
    thread_depth: int,
    post_date_ts: Optional[float] = None,
    *,
    campaign=None,
) -> bool:
    """Тред-симуляция: с шансом CONTINUE запускает ответ на свой коммент (≤ глубины).

    Отключается тумблером кампании (thread_simulation_enabled) — не всем
    нужны «мини-треды», и без явного выбора это выглядело как непонятные
    повторы в логе."""
    if comment_msg_id is None or thread_depth >= MAX_THREAD_DEPTH:
        return False
    if campaign is None:
        with ctx["session_factory"]() as session:
            campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None or not campaign.thread_simulation_enabled:
        return False
    if _rng(ctx).random() >= THREAD_CONTINUE_PROB:
        return False
    await _task_queue(ctx).enqueue(
        TaskName.COMMENTING_ON_NEW_POST,
        campaign_id,
        channel_msg_id,
        in_reply_to=comment_msg_id,
        thread_depth=thread_depth + 1,
        post_date_ts=post_date_ts,
    )
    get_logger().info(
        "commenting.thread.continue",
        campaign_id=campaign_id,
        in_reply_to=comment_msg_id,
        next_depth=thread_depth + 1,
    )
    return True


# --- аккаунт-центричный мониторинг (у каждого аккаунта свои каналы) -----------
#
# Отличие от campaign-центричного on_new_post: пост в отслеживаемом канале
# комментирует ИМЕННО тот аккаунт, у которого этот канал в работе (эффект
# «сообщества» возникает, когда один канал мониторят несколько аккаунтов — у
# каждого свой слушатель и свой коммент). Discussion-группа берётся из строки
# MonitoredChannel, а не из кампании.
#
# Задел на будущее: on_channel_post уже получает discussion_group_id и id поста,
# поэтому будущая задача «ответить на чужой (человеческий) коммент под постом»
# сможет читать ветку этой же группы и отвечать по теме поста + теме коммента
# (см. параметр in_reply_to, который прокидывается насквозь в post_channel_comment).


def _account_campaign(session, account_id: int):
    """Кампания аккаунта (через CampaignAccount) или (None, None)."""
    link = CampaignAccountRepository(session).get_by_account(account_id)
    if link is None:
        return None, None
    return link.campaign_id, CampaignRepository(session).get(link.campaign_id)


async def on_channel_post(
    ctx: dict,
    account_id: int,
    monitored_channel_id: int,
    channel_msg_id: int,
    in_reply_to: Optional[int] = None,
    thread_depth: int = 0,
    post_date_ts: Optional[float] = None,
    post_text: Optional[str] = None,
    prescheduled: bool = False,
) -> int:
    """Пост в канале аккаунта → запланировать ОДИН коммент этим аккаунтом.

    ``prescheduled=True`` (из бэкфилла): время уже разнесено планировщиком, свою
    случайную задержку не добавляем — иначе задержка накладывается дважды.
    """
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None or account.status != "assigned":
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="not_assigned")
            return 0
        campaign_id, campaign = _account_campaign(session, account_id)
        if campaign is None or not campaign.enabled:
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="no_campaign")
            return 0
        if _scheduled_not_yet(campaign, now):
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="scheduled_not_started")
            return 0
        ch = MonitoredChannelRepository(session).get(monitored_channel_id)
        ch_name = (ch.title or ch.channel_ref or ch.input_ref) if ch else "?"
        if not is_within_active_hours(now, campaign):
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="inactive_hours")
            _push(ctx, campaign_id, TimelineKind.COMMENT_SKIPPED,
                  f"Пост #{channel_msg_id} в «{ch_name}»: пропуск — вне активных часов кампании.",
                  {"reason": "inactive_hours", "account_id": account_id})
            return 0
        reason = _limit_skip_reason(session, campaign, post_date_ts, now)
        if reason:
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason=reason)
            _push(ctx, campaign_id, TimelineKind.COMMENT_SKIPPED,
                  f"Пост #{channel_msg_id} в «{ch_name}»: пропуск — {_skip_label(reason)}.",
                  {"reason": reason, "account_id": account_id})
            return 0

        if ch is None or ch.status != "working" or ch.discussion_group_id is None:
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="channel_not_working")
            return 0
        discussion_group_id = ch.discussion_group_id
        # Дедуп: один пост в группе = один коммент аккаунта. Ключ по
        # discussion_group_id (а НЕ monitored_channel_id) — иначе две строки
        # мониторинга на один и тот же канал/группу давали РАЗНЫЕ ключи и
        # проскакивали оба (симптом «всё равно по два раза»). Разные группы не
        # коллизируют: id группы в ключе.
        dedup_key = (
            f"commenting:onpost:{account_id}:{discussion_group_id}:"
            f"{channel_msg_id}:{thread_depth}:{in_reply_to or 0}"
        )
        if not _claim_once(ctx, dedup_key):
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="duplicate")
            return 0
        if _blacklisted(session, campaign_id, chat_id=ch.channel_tg_id, ref=ch.channel_ref):
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="blacklisted")
            _push(ctx, campaign_id, TimelineKind.COMMENT_SKIPPED,
                  f"Пост #{channel_msg_id} в «{ch_name}»: пропуск — канал в чёрном списке.",
                  {"reason": "blacklisted", "account_id": account_id})
            return 0

        # Фильтр отбора постов (post_selection_mode): по ключевым словам /
        # вероятности. В аккаунт-центричном мониторинге он раньше НЕ применялся
        # (баг-репорт: «режим по ключевому слову, а коммент на любой пост»).
        # Тред-продолжения (in_reply_to задан) не фильтруем — это ответ на свой
        # же коммент, пост уже прошёл отбор при первом касании.
        if in_reply_to is None:
            from modules.commenting.worker.listener import _passes_post_filter

            if not _passes_post_filter(
                post_text,
                mode=campaign.post_selection_mode,
                keywords=campaign.keywords or [],
                probability_percent=campaign.probability_percent,
                rng=rng,
            ):
                log.info(
                    "commenting.on_channel_post.skip",
                    account_id=account_id,
                    channel_msg_id=channel_msg_id,
                    reason="post_filter",
                    mode=campaign.post_selection_mode,
                )
                _push(ctx, campaign_id, TimelineKind.POST_FILTERED,
                      f"Пост #{channel_msg_id} в «{ch_name}»: пропуск — не прошёл отбор "
                      f"({campaign.post_selection_mode}).",
                      {"reason": "post_filter", "mode": campaign.post_selection_mode,
                       "account_id": account_id, "channel_msg_id": channel_msg_id})
                return 0

        # in_reply_to задан ТОЛЬКО для тред-продолжения (аккаунт отвечает сам
        # себе после своего же коммента) — отличаем в сообщении, иначе выглядит
        # как «тот же пост поймали ещё раз» (баг-репорт: «ловит пост и
        # коментит, а потом снова ловит тот же пост»).
        gen_msg = (
            f"Продолжаю тред под своим комментом к посту #{channel_msg_id} в «{ch_name}» (акк. #{account_id})…"
            if in_reply_to is not None
            else f"Генерирую ответ на пост #{channel_msg_id} в «{ch_name}» (акк. #{account_id})…"
        )
        _push(ctx, campaign_id, TimelineKind.GENERATION_STARTED, gen_msg,
              {"account_id": account_id, "channel_msg_id": channel_msg_id})
        reply_target = in_reply_to if in_reply_to is not None else channel_msg_id
        # postbot/economy: LLM не зовём здесь вообще — см. on_new_post (тот же
        # приём) и modules/commenting/worker/delivery.py (deliver_postbot/
        # deliver_economy).
        mode = _skip_llm_mode(campaign)
        if mode != "normal":
            text, ok = "", True
        else:
            provider = ctx.get("llm_provider") or get_provider(campaign.llm_provider)
            context = _thread_context(session, campaign_id, channel_msg_id, post_text)
            try:
                # Жёсткий потолок на генерацию: даже если у провайдера нет своего
                # таймаута, «Генерирую…» не зависает навсегда. Ошибку показываем.
                text, ok = await asyncio.wait_for(
                    _generate(ctx, session, campaign, account, provider, context),
                    timeout=_GENERATE_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                log.warning("commenting.on_channel_post.generate_timeout", account_id=account_id)
                _push(ctx, campaign_id, TimelineKind.COMMENT_FAILED,
                      f"Генерация ответа зависла (> {_GENERATE_TIMEOUT_SEC}с) — проверьте "
                      "LLM-провайдера (ключ/доступ к API). Коммент не создан.",
                      {"reason": "generate_timeout", "account_id": account_id})
                return 0
            except Exception as exc:  # noqa: BLE001 — показываем причину, а не молчим
                log.warning("commenting.on_channel_post.generate_failed",
                            account_id=account_id, error=repr(exc))
                _push(ctx, campaign_id, TimelineKind.COMMENT_FAILED,
                      f"Ошибка генерации ответа: {type(exc).__name__}: {exc}. "
                      "Проверьте LLM-провайдера (ключ/доступ). Коммент не создан.",
                      {"reason": "generate_failed", "account_id": account_id,
                       "error": repr(exc)[:200]})
                return 0
            if not ok:
                _log_below_min_words(session, campaign, account_id, channel_msg_id, text, reply_target)
                log.info("commenting.on_channel_post.skip", account_id=account_id, reason="below_min_words")
                _push(ctx, campaign_id, TimelineKind.COMMENT_SKIPPED,
                      f"Пост #{channel_msg_id} в «{ch_name}»: ответ короче минимума "
                      f"({campaign.min_words} слов) — пропуск.",
                      {"reason": "below_min_words", "account_id": account_id})
                return 0
        delay = (
            0.0
            if prescheduled
            else rng.uniform(campaign.posting_delay_min_sec, campaign.posting_delay_max_sec)
        )

    run_at = now + timedelta(seconds=delay)
    await task_queue.schedule(
        TaskName.COMMENTING_POST_CHANNEL_COMMENT,
        run_at,
        account_id,
        campaign_id,
        discussion_group_id,
        text,
        channel_msg_id,
        reply_target,
        thread_depth=thread_depth,
        post_date_ts=post_date_ts,
        post_text=post_text if mode == "economy" else None,
        economy_stub=mode == "economy",
        postbot_forward=mode == "postbot",
    )
    log.info(
        "commenting.on_channel_post.scheduled",
        account_id=account_id, channel_msg_id=channel_msg_id, thread_depth=thread_depth,
    )
    eta = _fmt_local(run_at, campaign)
    _push(ctx, campaign_id, TimelineKind.COMMENT_SCHEDULED,
          f"Ответ на пост #{channel_msg_id} в «{ch_name}» готов — опубликую через "
          f"{int(delay)}с (~{eta}).",
          {"account_id": account_id, "channel_msg_id": channel_msg_id, "delay_sec": int(delay)})
    return 1


async def post_channel_comment(
    ctx: dict,
    account_id: int,
    campaign_id: int,
    discussion_group_id: int,
    text: str,
    channel_msg_id: int,
    in_reply_to_message_id: int,
    thread_depth: int = 0,
    post_date_ts: Optional[float] = None,
    post_text: Optional[str] = None,
    economy_stub: bool = False,
    postbot_forward: bool = False,
) -> Optional[int]:
    """Постит коммент аккаунта в discussion-группу его канала (+ governor)."""
    now = _now(ctx)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    task_queue = _task_queue(ctx)
    log = get_logger()

    async def reschedule(run_at: datetime) -> None:
        await task_queue.schedule(
            TaskName.COMMENTING_POST_CHANNEL_COMMENT,
            run_at,
            account_id,
            campaign_id,
            discussion_group_id,
            text,
            channel_msg_id,
            in_reply_to_message_id,
            thread_depth=thread_depth,
            post_date_ts=post_date_ts,
            post_text=post_text,
            economy_stub=economy_stub,
            postbot_forward=postbot_forward,
        )

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is not None:
            reason = _limit_skip_reason(session, campaign, post_date_ts, now)
            if reason:
                log.info("commenting.post_channel_comment.skip", account_id=account_id, reason=reason)
                _push(ctx, campaign_id, TimelineKind.COMMENT_SKIPPED,
                      f"Коммент на пост #{channel_msg_id} (акк. #{account_id}) не отправлен "
                      f"— {_skip_label(reason)}.",
                      {"reason": reason, "account_id": account_id})
                return None
            wait = limits.pause_wait_until(
                CampaignAccountRepository(session).get(campaign_id, account_id), campaign, now
            )
            if wait is not None:
                await reschedule(wait)
                log.info("commenting.post_channel_comment.paused", account_id=account_id, until=wait.isoformat())
                _push(ctx, campaign_id, TimelineKind.COMMENT_SCHEDULED,
                      f"Коммент (акк. #{account_id}) отложен до "
                      f"{_fmt_local(wait, campaign)} — пауза между комментами.",
                      {"reason": "pause", "account_id": account_id})
                return None

    if not await _governor(ctx).check_and_reserve(account_id, "comment"):
        await reschedule(now + timedelta(minutes=GOVERNOR_RETRY_MINUTES))
        log.info("commenting.post_channel_comment.rate_limited", account_id=account_id)
        _push(ctx, campaign_id, TimelineKind.COMMENT_SCHEDULED,
              f"Коммент (акк. #{account_id}) отложен на {GOVERNOR_RETRY_MINUTES} мин "
              "— сработал rate-limit (governor).",
              {"reason": "rate_limited", "account_id": account_id})
        return None

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        wait = limits.claim_post_slot(session, campaign, account_id, now) if campaign else None
    if wait is not None:
        await reschedule(wait)
        log.info("commenting.post_channel_comment.paused", account_id=account_id, until=wait.isoformat())
        _push(ctx, campaign_id, TimelineKind.COMMENT_SCHEDULED,
              f"Коммент (акк. #{account_id}) отложен до "
              f"{_fmt_local(wait, campaign)} — пауза между комментами.",
              {"reason": "pause", "account_id": account_id})
        return None

    with session_factory() as session:
        mon = next(
            (
                r
                for r in MonitoredChannelRepository(session).list_by_discussion_group(discussion_group_id)
                if r.account_id == account_id
            ),
            None,
        )
        mon_id = mon.id if mon else None
        mon_ref = mon.input_ref if mon else None
        mon_username = mon.channel_ref if mon else None
        mon_tg_id = mon.channel_tg_id if mon else None
        mon_name = (mon.title or mon.channel_ref or mon.input_ref) if mon else "?"

    # Кампания нужна для delivery.deliver_comment: use_stickers / attach_image /
    # write_as_channel читаются оттуда. Берём свежую (могли поменять флаги за
    # время между планированием и отправкой).
    with session_factory() as session:
        campaign_row = CampaignRepository(session).get(campaign_id)

    async def _generate_real() -> str:
        """Полноценная ИИ-генерация на месте — economy-пробник и safety net
        (см. post_comment._generate_real — тот же приём, своя копия тут из-за
        разной сигнатуры/контекста account-центричного пайплайна)."""
        with session_factory() as gen_session:
            gen_account = AccountRepository(gen_session).get(account_id)
            _, gen_campaign = _account_campaign(gen_session, account_id)
            gen_provider = ctx.get("llm_provider") or get_provider(gen_campaign.llm_provider)
            gen_context = _thread_context(gen_session, campaign_id, channel_msg_id, post_text)
            gen_text, ok = await _generate(ctx, gen_session, gen_campaign, gen_account, gen_provider, gen_context)
            return gen_text if ok else delivery.stub_text(_rng(ctx))

    pool = _pool(ctx)
    client = await pool.get(account_id)
    try:
        # Таймаут на отправку: без него зависший Telethon-вызов (проблемы прокси/
        # сети) держит коммент в «вечной загрузке» молча. Падаем с понятной
        # ошибкой в таймлайн вместо бесконечного ожидания. Один общий таймаут на
        # капчу+доставку — economy добавляет к ней ещё ECONOMY_PROBE_DELAY_SEC,
        # укладывается с запасом в _DELIVER_TIMEOUT_SEC (90с).
        async def _do_deliver():
            if campaign_row.captcha_solving_enabled:
                await _maybe_solve_captcha(ctx, client, account_id, discussion_group_id, campaign_row, now)
            if postbot_forward and campaign_row.postbot_forward_enabled and campaign_row.postbot_message_ids:
                sent_, mode_, picked_id = await delivery.deliver_postbot(
                    ctx, client, campaign_row,
                    account_id=account_id,
                    discussion_group_id=discussion_group_id,
                    reply_to=in_reply_to_message_id,
                    now=now,
                    publisher=publisher,
                    rng=_rng(ctx),
                )
                return sent_, mode_, f"[Postbot #{picked_id}]", False
            if economy_stub and campaign_row.token_economy_enabled:
                sent_, mode_, final_ = await delivery.deliver_economy(
                    ctx, client, campaign_row,
                    account_id=account_id,
                    discussion_group_id=discussion_group_id,
                    reply_to=in_reply_to_message_id,
                    now=now,
                    publisher=publisher,
                    rng=_rng(ctx),
                    generate_real=_generate_real,
                )
                return sent_, mode_, final_, True
            send_text = text
            if not send_text:
                # Safety net: пустой text — scheduling был под economy/postbot,
                # а кампания успела сменить режим до отправки.
                send_text = await _generate_real()
            sent_, mode_ = await delivery.deliver_comment(
                ctx, client, campaign_row,
                account_id=account_id,
                discussion_group_id=discussion_group_id,
                text=send_text,
                reply_to=in_reply_to_message_id,
                now=now,
                publisher=publisher,
                rng=_rng(ctx),
            )
            return sent_, mode_, send_text, False

        sent, delivery_mode, final_text, is_economy = await asyncio.wait_for(
            _do_deliver(), timeout=_DELIVER_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        _push(ctx, campaign_id, TimelineKind.COMMENT_FAILED,
              f"Публикация в «{mon_name}» зависла (> {_DELIVER_TIMEOUT_SEC}с) — "
              "вероятно прокси/сеть аккаунта. Коммент не отправлен.",
              {"account_id": account_id, "error": "deliver_timeout"})
        log.warning("commenting.post_channel_comment.timeout", account_id=account_id)
        return None
    except ACCESS_ERRORS as exc:
        _push(ctx, campaign_id, TimelineKind.COMMENT_FAILED,
              f"Ошибка публикации в «{mon_name}»: нет доступа ({type(exc).__name__}). "
              "Канал мог снять обсуждения/забанить аккаунт.",
              {"account_id": account_id, "error": type(exc).__name__})
        await _handle_access_error(
            ctx, exc, campaign_id=campaign_id, account_id=account_id,
            channel_msg_id=channel_msg_id, text=text, reply_to=in_reply_to_message_id,
            channel_ref=mon_ref, channel_tg_id=mon_tg_id, monitored_channel_id=mon_id,
            blacklist_username=mon_username,
        )
        return None
    except Exception as exc:  # noqa: BLE001 — любую иную ошибку тоже показываем
        _push(ctx, campaign_id, TimelineKind.COMMENT_FAILED,
              f"Ошибка публикации в «{mon_name}»: {type(exc).__name__}: {exc}",
              {"account_id": account_id, "error": repr(exc)[:200]})
        log.warning("commenting.post_channel_comment.failed",
                    account_id=account_id, error=repr(exc))
        return None
    finally:
        await pool.release(account_id)

    if delivery_mode == "economy_failed":
        with session_factory() as session:
            CommentLogRepository(session).create(
                CommentLogCreate(
                    campaign_id=campaign_id,
                    account_id=account_id,
                    post_channel_msg_id=channel_msg_id,
                    comment_text=final_text,
                    status=CommentStatus.FAILED,
                    in_reply_to_message_id=in_reply_to_message_id,
                    error="economy_probe_failed",
                    is_economy_stub=True,
                    channel_ref=mon_name,
                )
            )
            session.commit()
        log.info("commenting.post_channel_comment.economy_probe_failed", account_id=account_id)
        _push(
            ctx, campaign_id, TimelineKind.COMMENT_FAILED,
            f"Экономия токенов (акк. #{account_id}) в «{mon_name}»: заглушка не прошла "
            "(удалена ботом/модератором) — ИИ не вызывался, токены сэкономлены.",
            {"account_id": account_id, "reason": "economy_probe_failed"},
        )
        return None

    posted_message_id = getattr(sent, "id", None)
    comment_log_id = None
    with session_factory() as session:
        row = CommentLogRepository(session).create(
            CommentLogCreate(
                campaign_id=campaign_id,
                account_id=account_id,
                post_channel_msg_id=channel_msg_id,
                comment_text=final_text,
                status=CommentStatus.POSTED,
                posted_message_id=posted_message_id,
                in_reply_to_message_id=in_reply_to_message_id,
                is_economy_stub=is_economy,
                channel_ref=mon_name,
            )
        )
        session.commit()
        comment_log_id = row.id
    # Verify-after-post (E4.2): расписываем задачу тем же аккаунтом на now +
    # verify_delay_sec. Кампанию берём свежую — verify_after_post могли
    # включить/выключить между планированием и отправкой коммента.
    await _schedule_verify(ctx, campaign_id, comment_log_id, posted_message_id, now)

    log.info(
        "commenting.post_channel_comment.posted",
        account_id=account_id, posted_message_id=posted_message_id, thread_depth=thread_depth,
    )
    _push(ctx, campaign_id, TimelineKind.COMMENT_POSTED,
          f"Коммент опубликован в «{mon_name}» (акк. #{account_id}) ✓",
          {"account_id": account_id, "posted_message_id": posted_message_id,
           "channel_msg_id": channel_msg_id})
    await maybe_continue_channel_thread(
        ctx, account_id, channel_msg_id, posted_message_id, thread_depth, post_date_ts,
        campaign=campaign_row,
    )
    return posted_message_id


async def maybe_continue_channel_thread(
    ctx: dict,
    account_id: int,
    channel_msg_id: int,
    comment_msg_id: Optional[int],
    thread_depth: int,
    post_date_ts: Optional[float] = None,
    *,
    campaign=None,
) -> bool:
    """Тред-симуляция для аккаунт-центричной ветки (ответ на свой же коммент).

    Отключается тумблером кампании (thread_simulation_enabled)."""
    if comment_msg_id is None or thread_depth >= MAX_THREAD_DEPTH:
        return False
    if campaign is not None and not campaign.thread_simulation_enabled:
        return False
    if _rng(ctx).random() >= THREAD_CONTINUE_PROB:
        return False
    # monitored_channel_id не нужен для повторного матчинга: on_channel_post
    # сам возьмёт discussion-группу по working-каналу аккаунта; но здесь мы уже
    # знаем discussion-группу — переиспользуем on_channel_post по каналу.
    with ctx["session_factory"]() as session:
        working = MonitoredChannelRepository(session).list_working_by_account(account_id)
    if not working:
        return False
    await _task_queue(ctx).enqueue(
        TaskName.COMMENTING_ON_CHANNEL_POST,
        account_id,
        working[0].id,
        channel_msg_id,
        in_reply_to=comment_msg_id,
        thread_depth=thread_depth + 1,
        post_date_ts=post_date_ts,
    )
    get_logger().info(
        "commenting.channel_thread.continue",
        account_id=account_id, in_reply_to=comment_msg_id, next_depth=thread_depth + 1,
    )
    return True
