"""Человекочитаемое описание действия прогрева для UI (лента «Активность»).

Из ``action_type`` + ``target`` + ``meta`` собирает короткую фразу вида
«👍 на пост в @durov» или «прочитал 24 сообщения в @telegram». Используется и
дашбордом, и списком активности аккаунта — чтобы детали были одинаковыми.
"""

from __future__ import annotations

from typing import Any, Optional


def _handle(target: Optional[str]) -> str:
    """Нормализует цель к виду @username (если это похоже на username)."""
    if not target:
        return ""
    t = str(target).strip()
    if t.startswith("@") or "://" in t or "/" in t or " " in t:
        return t
    return f"@{t}"


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
        err = meta.get("error_category") or "ошибка"
        return f"не удалось ({err})"
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
            return "искал peer для взаимодействия"
        extra = ", реакция 👀" if meta.get("reacted") else ""
        return f"взаимодействие с {where}{extra}"
    # fallback — сырой тип.
    return action_type.replace("_", " ")
