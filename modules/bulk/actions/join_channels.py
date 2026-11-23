"""Bulk-action: массово подписаться на набор каналов (этап 8 УТП).

Для КАЖДОГО аккаунта прогоняем список ``channel_refs`` и вступаем/присоединяемся.
Публичные каналы (@name / t.me/name) — ``JoinChannelRequest`` по entity;
инвайты (t.me/+hash / joinchat/hash) — ``ImportChatInviteRequest``;
папки-addlist (t.me/addlist/slug) — при ``expand_folders=True`` (по умолчанию)
разворачиваем в дочерние каналы через :mod:`worker.telegram_folders`
(этап 8, backlog #2). ``expand_folders=False`` — старое поведение (папка идёт
в ``errors['folders_unsupported_in_bulk']``).

Если один ref упал ОБЫЧНОЙ ошибкой — остальные всё равно попробуем, результат
по каждому в ``detail.joined`` / ``detail.errors``. Но если Telegram ответил
``FloodWaitError`` — дальше НЕ идём: ещё один вызов почти наверняка тоже
упадёт тем же флудвейтом (лимит общий на метод/аккаунт, не на конкретный
чат), а долбить оставшиеся ref'ы подряд без паузы — это и есть прямой путь к
ещё более долгому флудвейту. Вместо этого прерываемся, фиксируем, на каком
ref'е остановились, и кладём оставшиеся необработанные в
``detail.not_attempted`` — их можно ретраить отдельным запуском позже.

ПАУЗЫ МЕЖДУ ПОДПИСКАМИ: между каждым join'ом — случайная пауза
(:func:`_pace_delay`), а не все 100 ссылок подряд без разрывов (именно так
аккаунты и ловят флудвейт при массовой вставке большого списка). Пауза
адаптивная: чем длиннее список, тем она короче, чтобы уложиться в
``item_timeout_seconds`` (см. регистрацию action'а ниже) — это НЕ железная
гарантия от флудвейта (точные лимиты Telegram не публикуются и зависят от
возраста/доверия аккаунта), а защита «лучше, чем вообще без пауз». Для
списков в районе 60–100 ссылок всё равно безопаснее разбивать их на
несколько более мелких запусков (по 15–25 ссылок) в разное время, а не
слать одним массивом.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call
from worker.telegram_folders import join_folder
from worker.telegram_refs import classify_ref, folder_slug, invite_hash, public_ref

# Таймаут на один item (один аккаунт) для ЭТОГО действия — override дефолтных
# 180с (worker/tasks/bulk.py::_ITEM_TIMEOUT_SECONDS). При max_length=100 и
# паузах ниже нужен запас на весь список + сами сетевые вызовы.
_ITEM_TIMEOUT_SECONDS = 20 * 60

# Безопасный запас: таймаут минус время на сами Telethon-вызовы (join/resolve)
# и небольшой буфер на всякий случай — остальное распределяем под паузы.
_CALL_OVERHEAD_SECONDS_PER_REF = 3
_SAFETY_MARGIN_SECONDS = 45

# Пауза между join'ами не короче/не длиннее этих значений, какой бы длинный
# ни был список (иначе на огромном списке адаптивная формула уйдёт в 0-1с —
# это уже не пауза, а обратно тот же флуд).
_MIN_DELAY_SECONDS = 8.0
_MAX_DELAY_SECONDS = 35.0


def _pace_delay(total_refs: int) -> float:
    """Случайная пауза перед следующим join'ом, подогнанная под длину списка,
    чтобы уложиться в ``_ITEM_TIMEOUT_SECONDS`` с запасом."""
    if total_refs <= 1:
        return 0.0
    budget = (
        _ITEM_TIMEOUT_SECONDS
        - _SAFETY_MARGIN_SECONDS
        - _CALL_OVERHEAD_SECONDS_PER_REF * total_refs
    )
    avg_delay = max(budget / (total_refs - 1), 0.0)
    lo = min(_MIN_DELAY_SECONDS, avg_delay) if avg_delay < _MIN_DELAY_SECONDS else _MIN_DELAY_SECONDS
    hi = min(max(avg_delay, lo), _MAX_DELAY_SECONDS)
    return random.uniform(lo, hi)


class JoinChannelsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_refs: list[str] = Field(min_length=1, max_length=100)
    # Backlog #этап8.4: разворачивать addlist-папки в дочерние каналы. По
    # умолчанию — включено (иначе фича не будет использоваться).
    expand_folders: bool = True


async def _run(
    *,
    account_id: int,
    payload: JoinChannelsPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    joined: list[str] = []
    errors: dict[str, str] = {}
    # Для папок — метаинформация: {slug: {joined: [...], already_in: N}}.
    folder_meta: dict[str, dict] = {}
    not_attempted: list[str] = []
    total = len(payload.channel_refs)

    for idx, raw in enumerate(payload.channel_refs):
        # Пауза ПЕРЕД каждым join'ом, кроме самого первого — иначе список из
        # 60-100 ссылок улетает в Telegram практически одним залпом, что и
        # вызывает флудвейт у аккаунта (см. docstring модуля).
        if idx > 0:
            await asyncio.sleep(_pace_delay(total))

        kind = classify_ref(raw)
        try:
            if kind == "invite":
                await around_telethon_call(
                    lambda h=invite_hash(raw): client(ImportChatInviteRequest(h)),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
            elif kind == "folder":
                if not payload.expand_folders:
                    errors[raw] = "folders_unsupported_in_bulk"
                    continue
                slug = folder_slug(raw)
                if slug is None:
                    errors[raw] = "bad_folder_slug"
                    continue
                result = await join_folder(
                    client,
                    slug,
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
                folder_meta[raw] = {
                    "joined": result.joined_refs,
                    "already_in": result.already_in,
                }
                joined.extend(result.joined_refs)
                # Сам addlist-ref не помечаем в joined отдельно: он «служебный»,
                # его дочерние каналы уже в списке.
                continue
            else:
                entity = await around_telethon_call(
                    lambda r=public_ref(raw): client.get_entity(r),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
                await around_telethon_call(
                    lambda e=entity: client(JoinChannelRequest(e)),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
            joined.append(raw)
        except FloodWaitError as exc:
            # around_telethon_call уже записал health-инцидент и cooldown для
            # аккаунта (см. worker/health/monitor.py). Тут — не ПЕРЕХОДИМ к
            # следующему ref'у: лимит общий на метод/аккаунт, следующий вызов
            # почти гарантированно упадёт тем же флудвейтом. Останавливаемся,
            # оставшиеся ref'ы — в not_attempted, их можно ретраить позже
            # отдельным запуском (когда cooldown пройдёт).
            errors[raw] = repr(exc)
            not_attempted.extend(payload.channel_refs[idx + 1 :])
            break
        except Exception as exc:  # noqa: BLE001 - фиксируем per-ref, идём дальше
            errors[raw] = repr(exc)

    ok = bool(joined) or not errors
    detail: dict[str, Any] = {"joined": joined, "errors": errors}
    if folder_meta:
        detail["folders"] = folder_meta
    if not_attempted:
        detail["not_attempted"] = not_attempted
        detail["stopped_reason"] = "flood_wait"
        if not ok:
            # ok=False означает, что флудвейт случился уже на первом ref'е
            # (joined пуст) — отдаём reason/error верхнего уровня, чтобы
            # worker/tasks/bulk.py::_error_from_detail показал внятную причину
            # вместо общего "action_returned_not_ok".
            detail["reason"] = "flood_wait"
            detail["error"] = next(iter(errors.values()), None)
    return BulkActionResult(ok=ok, detail=detail)


register(
    BulkAction(
        name=BulkActionType.JOIN_CHANNELS.value,
        requires_client=True,
        payload_schema=JoinChannelsPayload,
        run=_run,
        title="Подписаться на каналы",
        description=(
            "Массово вступает каждым аккаунтом в переданный набор каналов. "
            "Между подписками — пауза, чтобы не словить флудвейт; при флудвейте "
            "останавливается и не трогает остаток списка."
        ),
        governor_key="bulk_channel",
        item_timeout_seconds=_ITEM_TIMEOUT_SECONDS,
    )
)
