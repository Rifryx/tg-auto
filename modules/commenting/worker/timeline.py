"""Легковесный таймлайн событий кампании (listener + runner).

Хранится в Redis как capped-list (LPUSH + LTRIM), TTL 24h. Пользователь
жаловался: «в блоке запущенной кампании нет логов — что где когда (пост
получен, подготовился ответ, опубликован, реакция поставлена)». Чтобы не
плодить миграцию и таблицу под каждый тик listener'а, пишем сюда — короткий
live-feed с последними ~200 событиями. Для долговременной истории есть
отдельный ``CommentLog`` (posted/failed/flagged).

Публичный API — три функции: ``push_event`` (воркер), ``recent_events``
(API/UI), и enum ``TimelineKind`` под подписи.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

# Сколько событий держать в хвосте и как долго, если ничего нового не пишется.
# Capped-list: при каждом push старое за пределами лимита удаляется (LTRIM) —
# лента не растёт бесконечно (жалоба на «склад логов»).
_LIMIT = 150
_TTL_SECONDS = 24 * 3600


def _key(campaign_id: int) -> str:
    return f"commenting:timeline:{campaign_id}"


class TimelineKind(str, Enum):
    """Короткая номенклатура событий — чтобы UI рисовал иконку/подпись."""

    LISTENER_ONLINE = "listener_online"      # слушатель поднялся на канале
    LISTENER_OFFLINE = "listener_offline"    # слушатель упал/перезапуск
    POST_RECEIVED = "post_received"          # пост канала пойман
    POST_FILTERED = "post_filtered"          # отсеян фильтром кампании
    POST_QUEUED = "post_queued"              # поставлен в очередь
    GENERATION_STARTED = "generation_started"  # LLM пошёл генерить коммент
    COMMENT_POSTED = "comment_posted"        # коммент опубликован
    COMMENT_FAILED = "comment_failed"        # ошибка при публикации
    REACTION_SET = "reaction_set"            # поставлена реакция
    NO_ACCOUNT = "no_account"                # не нашлось свободного аккаунта


@dataclass(frozen=True)
class TimelineEvent:
    ts: float
    kind: str
    message: str
    meta: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {"ts": self.ts, "kind": self.kind, "message": self.message, "meta": self.meta},
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: Any) -> Optional["TimelineEvent"]:
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if not isinstance(raw, str):
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return cls(
            ts=float(data.get("ts") or 0.0),
            kind=str(data.get("kind") or "unknown"),
            message=str(data.get("message") or ""),
            meta=data.get("meta") if isinstance(data.get("meta"), dict) else {},
        )


def push_event(
    redis: Any,
    campaign_id: int,
    kind: str | TimelineKind,
    message: str,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    """Записать событие в хвост таймлайна кампании.

    ``redis`` — любой клиент с методами lpush/ltrim/expire (sync или async-sync
    обёрткой; в worker'е прилетает синхронный клиент из ctx). Исключения не
    пробрасываем: таймлайн — вспомогательный, он не должен ронять listener.
    """
    if redis is None:
        return
    kind_value = kind.value if isinstance(kind, TimelineKind) else str(kind)
    event = TimelineEvent(
        ts=time.time(),
        kind=kind_value,
        message=message,
        meta=meta or {},
    )
    try:
        key = _key(campaign_id)
        pipe = redis.pipeline()
        pipe.lpush(key, event.to_json())
        pipe.ltrim(key, 0, _LIMIT - 1)
        pipe.expire(key, _TTL_SECONDS)
        pipe.execute()
    except Exception:  # noqa: BLE001 — таймлайн не должен ронять воркер
        pass


def recent_events(redis: Any, campaign_id: int, limit: int = 100) -> list[TimelineEvent]:
    """Прочитать последние N событий таймлайна кампании (сначала новые).

    Исключения проглатываем — пустой список лучше, чем 500 на API.
    """
    if redis is None:
        return []
    try:
        raw = redis.lrange(_key(campaign_id), 0, max(0, limit - 1))
    except Exception:  # noqa: BLE001
        return []
    events: list[TimelineEvent] = []
    for item in raw or []:
        parsed = TimelineEvent.from_json(item)
        if parsed is not None:
            events.append(parsed)
    return events
