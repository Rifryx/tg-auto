"""Общие хелперы парсеров (вступление в чат, диагностика «мало собрано»)."""

from __future__ import annotations

from typing import Any, Optional


async def ensure_member(
    client: Any,
    entity: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Any = None,
    progress: Any = None,
    log: Any = None,
) -> None:
    """Best-effort вступление аккаунта-парсера в чат/группу перед чтением.

    Telethon у НЕ-участника почти всегда отдаёт лишь админов (или пусто) —
    отсюда «на чат 15k вернуло 2 юзернейма» и пустые ленты комментаторов.
    JoinChannel идемпотентен; если аккаунт уже внутри (``entity.left is False``)
    — не трогаем. Ошибку не роняем: читаем как есть."""
    if getattr(entity, "left", None) is False:
        return
    from telethon.tl.functions.channels import JoinChannelRequest

    from worker.health import around_telethon_call

    try:
        await around_telethon_call(
            lambda: client(JoinChannelRequest(entity)),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception as exc:  # noqa: BLE001 — join best-effort
        if log is not None:
            log.info("parsing.join_skipped", error=repr(exc))
        if progress is not None:
            progress.log(
                "Не удалось вступить аккаунтом-парсером — читаю как есть "
                f"({type(exc).__name__})."
            )


def diagnose_scarce(progress: Any, chat_ref: str, total_seen: int, *, threshold: int = 5) -> None:
    """Если собрано подозрительно мало — подсказываем пользователю почему."""
    if progress is None or total_seen > threshold:
        return
    progress.log(
        f"⚠ Из «{chat_ref}» видно лишь {total_seen}. Обычно это значит, что "
        "аккаунт-парсер не состоит в чате/канале, либо чат скрывает участников "
        "(большие/закрытые группы). Добавьте аккаунт вручную и повторите, либо "
        "используйте другой режим (комментаторы/сообщения/реакции)."
    )


def apply_max_targets(max_targets: Optional[int], current: int) -> bool:
    """True, если достигнут лимит и сбор пора прекращать."""
    return max_targets is not None and current >= max_targets
