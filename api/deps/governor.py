"""Провайдер async-Governor для API-слоя (rate-limit по аккаунту).

Тот же ``worker.health.Governor`` используется в воркере (комментинг/прогрев).
Здесь — точка внедрения в bulk-эндпоинты, чтобы не ставить сотни задач подряд
на один аккаунт и не превращать «проверь всех» в DoS собственной инфраструктуры.
"""

from __future__ import annotations

from functools import lru_cache

import redis.asyncio as aioredis

from core.config import get_settings
from worker.health.governor import Governor


@lru_cache
def _redis() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url)


def get_health_governor() -> Governor:
    return Governor(_redis())
