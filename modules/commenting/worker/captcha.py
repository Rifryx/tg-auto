"""Решение капчи (BETA): ИИ проходит анти-спам проверку бота обсуждения.

Некоторые группы обсуждений держат анти-спам бота (CombotAntiSpam, CAS,
Rose и т.п.), который на вход нового/подозрительного аккаунта требует пройти
проверку — текстовый вопрос («2+2=?», «напишите слово ниже»...) или кнопки
(«Я не бот» / выбрать правильный вариант). Пока проверка не пройдена, бот
обычно молча режет сообщения аккаунта (или банит после таймаута).

Эвристика (best-effort, никогда не роняет комментинг):
* смотрим последние ``_LOOKBACK`` сообщений группы обсуждения;
* берём САМОЕ СВЕЖЕЕ сообщение от бота, не старше ``_MAX_AGE_SEC`` — иначе
  рискуем отвечать на капчу, которая уже решена/просрочена, или на обычный
  пост бота-модератора;
* похоже на капчу — по ключевым словам или наличию inline-кнопок;
* текстовая/арифметическая — просим LLM короткий точный ответ, шлём реплаем;
* кнопочная — просим LLM выбрать ТОЧНЫЙ текст нужной кнопки среди
  предложенных и кликаем её (``message.click(text=...)``); не угадываем
  наугад — ошибка разбора/клика просто логируется, слепых кликов нет
  (неверный клик может доусугубить бан).

НЕ поддержано (осознанно, v1): капчи-картинки (нужен vision-провайдер —
worker/llm сейчас только текстовый, см. worker/llm/base.py). Такие просто
логируются и пропускаются — комментинг продолжается как есть (скорее всего
неудачно, но без лишних ИИ-вызовов вслепую).

Кэш «один пробник на группу»: решаем максимум ОДИН раз на (account, group) —
последующие комменты того же аккаунта в той же группе больше не проверяют
(ключ в redis_sync, TTL ``_CACHE_TTL_SEC``). Это тот же принцип, что у
конкурента («Один пробник на группу — далее из кэша»): антиспам-бот обычно
проверяет аккаунт один раз при первом контакте, а не на каждое сообщение.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from worker.health import around_telethon_call
from worker.llm import Message

get_logger = structlog.get_logger

_LOOKBACK = 15
_MAX_AGE_SEC = 10 * 60
_CACHE_TTL_SEC = 30 * 24 * 3600

_KEYWORD_RE = re.compile(
    r"капч|captcha|не\s*бот|not\s*a?\s*bot|подтверди|verify|human|"
    r"нажми|press|выбери|select",
    re.IGNORECASE,
)
_ARITHMETIC_RE = re.compile(r"\d+\s*[+\-*хx×]\s*\d+")


def _cache_key(account_id: int, discussion_group_id: int) -> str:
    return f"commenting:captcha_ok:{account_id}:{discussion_group_id}"


def _already_solved(ctx: dict, account_id: int, discussion_group_id: int) -> bool:
    r = ctx.get("redis_sync")
    if r is None:
        return False
    try:
        return bool(r.get(_cache_key(account_id, discussion_group_id)))
    except Exception:  # noqa: BLE001
        return False


def _mark_solved(ctx: dict, account_id: int, discussion_group_id: int) -> None:
    r = ctx.get("redis_sync")
    if r is None:
        return
    try:
        r.set(_cache_key(account_id, discussion_group_id), "1", ex=_CACHE_TTL_SEC)
    except Exception:  # noqa: BLE001
        pass


def _looks_like_captcha(msg: Any) -> bool:
    text = (getattr(msg, "message", None) or "") or ""
    if getattr(msg, "buttons", None):
        return True
    if _KEYWORD_RE.search(text):
        return True
    if _ARITHMETIC_RE.search(text) and len(text) < 300:
        return True
    return False


async def _find_challenge(ctx: dict, client, discussion_group_id: int, now: datetime) -> Optional[Any]:
    try:
        messages = await client.get_messages(discussion_group_id, limit=_LOOKBACK)
    except Exception as exc:  # noqa: BLE001
        get_logger().info("commenting.captcha.fetch_failed", error=repr(exc))
        return None
    for msg in messages or []:
        sender = getattr(msg, "sender", None)
        if sender is None:
            try:
                sender = await msg.get_sender()
            except Exception:  # noqa: BLE001
                sender = None
        if not getattr(sender, "bot", False):
            continue
        date = getattr(msg, "date", None)
        if date is not None:
            d = date if date.tzinfo else date.replace(tzinfo=timezone.utc)
            if (now - d).total_seconds() > _MAX_AGE_SEC:
                continue
        if _looks_like_captcha(msg):
            return msg
    return None


async def _ask_llm(provider, question: str, *, buttons: Optional[list[str]] = None) -> str:
    if buttons:
        system = (
            "Ты проходишь анти-спам проверку в Telegram-группе. Ниже — текст "
            "вопроса и варианты ответа (кнопки). Ответь ТОЛЬКО точным текстом "
            "ОДНОЙ правильной кнопки, без кавычек и пояснений."
        )
        user = f"Вопрос: {question}\n\nКнопки:\n" + "\n".join(f"- {b}" for b in buttons)
    else:
        system = (
            "Ты проходишь анти-спам проверку (капчу) в Telegram-группе. Ответь "
            "ТОЛЬКО коротким точным ответом на вопрос ниже — без пояснений, "
            "без лишних слов (если это арифметика — только число)."
        )
        user = question
    raw = await provider.generate(system, [Message(role="user", content=user)], max_tokens=30, temperature=0.0)
    return (raw or "").strip()


async def maybe_solve_captcha(
    ctx: dict,
    client,
    *,
    account_id: int,
    discussion_group_id: int,
    provider,
    publisher,
    now: datetime,
) -> None:
    """Best-effort: пытается пройти капчу, если она есть. Никогда не бросает —
    ошибки только логируются, обычный комментинг продолжается в любом случае.
    """
    if _already_solved(ctx, account_id, discussion_group_id):
        return
    log = get_logger()
    try:
        challenge = await _find_challenge(ctx, client, discussion_group_id, now)
    except Exception as exc:  # noqa: BLE001
        log.info("commenting.captcha.detect_failed", account_id=account_id, error=repr(exc))
        return
    if challenge is None:
        return

    text = (getattr(challenge, "message", None) or "").strip()
    buttons = getattr(challenge, "buttons", None)

    async def _call(factory):
        return await around_telethon_call(
            factory,
            account_id=account_id,
            session_factory=ctx["session_factory"],
            publisher=publisher,
            now=now,
        )

    if buttons:
        # buttons — список рядов кнопок (список списков Button-объектов).
        labels = [b.text for row in buttons for b in row if getattr(b, "text", None)]
        if not labels:
            # Кнопки без текста (эмодзи-пикчи и т.п.) — похоже на картиночную
            # капчу, которую мы не решаем (нет vision-провайдера).
            log.info("commenting.captcha.image_like_skipped", account_id=account_id)
            return
        try:
            answer = await _ask_llm(provider, text, buttons=labels)
        except Exception as exc:  # noqa: BLE001
            log.info("commenting.captcha.llm_failed", account_id=account_id, error=repr(exc))
            return
        picked = next((lbl for lbl in labels if lbl.strip().lower() == answer.strip().lower()), None)
        if picked is None:
            log.info(
                "commenting.captcha.button_not_matched",
                account_id=account_id, answer=answer, labels=labels,
            )
            return
        try:
            await _call(lambda: challenge.click(text=picked))
        except Exception as exc:  # noqa: BLE001
            log.info("commenting.captcha.click_failed", account_id=account_id, error=repr(exc))
            return
        log.info("commenting.captcha.button_clicked", account_id=account_id, picked=picked)
    else:
        if not text:
            return
        try:
            answer = await _ask_llm(provider, text)
        except Exception as exc:  # noqa: BLE001
            log.info("commenting.captcha.llm_failed", account_id=account_id, error=repr(exc))
            return
        if not answer:
            return
        try:
            await _call(
                lambda: client.send_message(
                    discussion_group_id, answer, reply_to=challenge.id
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.info("commenting.captcha.answer_send_failed", account_id=account_id, error=repr(exc))
            return
        log.info("commenting.captcha.text_answered", account_id=account_id, answer=answer)

    _mark_solved(ctx, account_id, discussion_group_id)
