"""Человекочитаемое описание действия прогрева для UI (лента «Активность»).

Из ``action_type`` + ``target`` + ``meta`` собирает короткую фразу вида
«👍 на пост в @durov» или «прочитал 24 сообщения в @telegram». Используется и
дашбордом, и списком активности аккаунта — чтобы детали были одинаковыми.
"""

from __future__ import annotations

from typing import Any, Optional

# Категории ошибок прогрева (worker/warming/actions/base._categorize_error) —
# в понятные пользователю фразы. Раньше в ленте светилось «не удалось
# (unknown)» / «(rate_limit)» — английские коды, которые ничего не говорят.
_ERROR_CATEGORY_RU: dict[str, str] = {
    "target_broken": "цель недоступна",
    "rate_limit": "слишком часто, ждём",
    "fatal": "аккаунт недоступен",
    "unknown": "неизвестная ошибка",
}

# Короткие пользовательские объяснения для частых имён исключений — чтобы
# в ленте было видно не «не удалось: неизвестная ошибка» (ни о чём), а
# конкретную причину. Если имя не в словаре — используется само имя класса
# (TimeoutError, ValueError и т.п.) — это всё равно информативнее, чем
# generic «неизвестная ошибка».
_ERROR_TYPE_RU: dict[str, str] = {
    "TimeoutError": "таймаут сети",
    "asyncio.TimeoutError": "таймаут сети",
    "ConnectionError": "нет соединения",
    "ConnectionResetError": "соединение сброшено",
    "ConnectionRefusedError": "сервер не принимает соединения",
    "OSError": "ошибка сети",
    "RuntimeError": "сбой выполнения",
    "ValueError": "некорректные данные",
    "AttributeError": "сбой во внутреннем состоянии",
    "KeyError": "не найден ожидаемый ключ",
    "UserNotParticipantError": "аккаунт не состоит в этом канале",
    "MessageIdInvalidError": "сообщение удалено",
    "MessageNotModifiedError": "сообщение не изменилось",
    "PasswordHashInvalidError": "неверный пароль 2FA",
    "PhoneCodeInvalidError": "неверный код",
    "RPCError": "ошибка Telegram-API",
    "ClientConnectorError": "нет соединения",
    "TypeError": "сбой во внутреннем состоянии",
    "NotImplementedError": "функция не реализована",
}


def _handle(target: Optional[str]) -> str:
    """Нормализует цель к виду @username (если это похоже на username)."""
    if not target:
        return ""
    t = str(target).strip()
    if t.startswith("@") or "://" in t or "/" in t or " " in t:
        return t
    return f"@{t}"


def _format_failed(meta: dict[str, Any]) -> str:
    """Собирает причину сбоя в короткую осмысленную фразу.

    Приоритет: (1) перевод error_type из _ERROR_TYPE_RU → (2) «сбой
    (ClassName)» если имя класса известно, но нет перевода → (3) категория
    error_category с переводом → (4) просто «ошибка». Так пользователь
    всегда видит что-то конкретнее, чем безликое «неизвестная ошибка»."""
    error_type = meta.get("error_type")
    if error_type:
        human = _ERROR_TYPE_RU.get(error_type)
        if human:
            return f"не удалось: {human}"
        # Имя класса в скобках — техподсказка; основная фраза остаётся
        # русской. Так инвариант «описание на русском» сохраняется, а у
        # пользователя есть зацепка для техподдержки.
        return f"не удалось: сбой ({error_type})"
    code = meta.get("error_category")
    if code:
        return f"не удалось: {_ERROR_CATEGORY_RU.get(code, 'ошибка')}"
    return "не удалось: ошибка"


def warming_detail(
    action_type: str,
    *,
    target: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    status: Optional[str] = None,
) -> str:
    """Короткое описание действия прогрева на русском."""
    meta = meta or {}
    if status == "failed":
        return _format_failed(meta)
    if status == "skipped":
        return "пропущено"

    where = _handle(target)
    if action_type == "reaction":
        emoji = meta.get("emoji") or "реакция"
        return f"{emoji} на пост в {where}" if where else f"{emoji} на пост"
    if action_type == "view_media":
        n = meta.get("viewed")
        base = f"просмотрел {n} сообщ." if n else "просмотрел медиа"
        return f"{base} в {where}" if where else base
    if action_type == "read_history":
        n = meta.get("read")
        base = f"прочитал {n} сообщ." if n else "прочитал историю"
        return f"{base} в {where}" if where else base
    if action_type == "subscribe_channel":
        return f"подписался на {where}" if where else "подписался на канал"
    if action_type == "join_group":
        return f"вступил в {where}" if where else "вступил в группу"
    if action_type == "idle_online":
        return "был онлайн"
    if action_type == "update_profile":
        field = meta.get("field") or "профиль"
        label = "«о себе»" if field == "bio" else field
        return f"обновил {label}"
    if action_type == "interact_with_peer":
        if not where:
            return "искал аккаунт для общения"
        extra = ", реакция 👀" if meta.get("reacted") else ""
        return f"общение с {where}{extra}"
    # fallback — сырой тип.
    return action_type.replace("_", " ")
