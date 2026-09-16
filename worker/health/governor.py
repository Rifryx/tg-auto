"""Rate-limit governor по аккаунту (PROJECT-STAGES §2, §5.3).

Счётчики — в Redis по ключу ``rl:acc:{id}:{action_type}:{window}`` с TTL окна.
Лимиты по умолчанию (кандидаты в config; core.config трогать нельзя):

* comment — 20/час, 100/сутки
* warming — 30/час, 200/сутки
* login   — 5/час

``check_and_reserve`` резервирует слот атомарно-достаточно для одного worker-
процесса: сперва проверка всех окон, затем инкремент. True — можно и слот занят,
False — лимит исчерпан (вызывающий откладывает действие).
"""

from __future__ import annotations

from typing import Any

_HOUR = 3600
_DAY = 86400

# action_type -> кортеж окон (имя окна, лимит, TTL секунд)
LIMITS: dict[str, tuple[tuple[str, int, int], ...]] = {
    "comment": (("hour", 20, _HOUR), ("day", 100, _DAY)),
    "warming": (("hour", 30, _HOUR), ("day", 200, _DAY)),
    "login": (("hour", 5, _HOUR),),
    # health.check_account: не даём заспамить одну и ту же карточку — 6/час,
    # 20/сутки достаточно и для ручного «Проверить», и для periodic-планировщика.
    "health_check": (("hour", 6, _HOUR), ("day", 20, _DAY)),
}


class Governor:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    @staticmethod
    def _key(account_id: int, action_type: str, window: str) -> str:
        return f"rl:acc:{account_id}:{action_type}:{window}"

    async def check_and_reserve(self, account_id: int, action_type: str) -> bool:
        """True и слот занят, если ни одно окно не превышено; иначе False."""
        if self._redis is None:
            # Без Redis лимитировать нечем — fail-open (не роняем прогрев/логин).
            return True
        windows = LIMITS.get(action_type)
        if windows is None:
            # Неизвестный тип действия не лимитируем (но и не роняем).
            return True

        # Фаза 1: проверка — если любое окно уже на лимите, ничего не резервируем.
        for window, limit, _ttl in windows:
            key = self._key(account_id, action_type, window)
            current = await self._redis.get(key)
            if current is not None and int(current) >= limit:
                return False

        # Фаза 2: резервирование во всех окнах.
        for window, _limit, ttl in windows:
            key = self._key(account_id, action_type, window)
            value = await self._redis.incr(key)
            if value == 1:
                await self._redis.expire(key, ttl)
        return True
