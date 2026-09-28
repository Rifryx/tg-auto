"""Проверка «тихих часов» цели (prompt 7.2, spec §11.2).

Executor вызывает :func:`is_quiet_hour_for` перед реальным TriggerRunner:
если у кампании включён ``quiet_hours_target`` и задана TZ, и локальное
время в этой зоне попадает в окно 00:00–07:00, executor записывает
``ExecutionOutcome.SKIPPED_QUIET`` без похода в MTProto.

Если TZ не задана — считаем, что гео цели неизвестно, и не блокируем
(так и записано в спеке: «Если гео нет — не блокируем»).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover — 3.11+ гарантирует наличие
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment]


QUIET_START_HOUR = 0
QUIET_END_HOUR = 7


def is_quiet_hour_for(
    tz_name: Optional[str],
    *,
    now: Optional[datetime] = None,
    start_hour: int = QUIET_START_HOUR,
    end_hour: int = QUIET_END_HOUR,
) -> bool:
    """True, если сейчас в ``tz_name`` локальный час ∈ [start, end).

    * ``tz_name`` None или неизвестная зона → False (не блокируем).
    * Диапазон интерпретируется как единый суточный интервал, не
      переваливающий через полночь (start<end).
    """
    if not tz_name or ZoneInfo is None:
        return False
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return False
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    local_hour = ref.astimezone(tz).hour
    return start_hour <= local_hour < end_hour


__all__ = ["QUIET_START_HOUR", "QUIET_END_HOUR", "is_quiet_hour_for"]
