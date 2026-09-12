"""Тела health-задач (PROJECT-STAGES §5.3).

* ``health.check_proxies`` (cron 10 мин): пингует прокси, обновляет
  ``proxies.status``/``last_checked_at``; для аккаунтов на мёртвом прокси в
  assigned/pool фиксирует ``HealthEvent(proxy_down)``, НЕ меняя статус аккаунта
  (решение оставляем пользователю).
* ``health.cooldown_return`` реализована в worker/tasks/handlers.py (возврат из
  cooldown через state machine) — здесь не дублируется.

Пробер прокси инъектируется через ``ctx['proxy_prober']`` (для тестов); по
умолчанию — простой TCP-connect (liveness).
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select

from core.enums import AccountStatus, HealthEventType, ProxyStatus
from core.models import Account
from core.repositories.health_event import HealthEventRepository
from core.repositories.proxy import ProxyRepository
from core.schemas.health import HealthEventCreate
from core.schemas.proxy import ProxyUpdate
from worker.tasks.logging import get_logger

_PROBE_TIMEOUT = 5.0
_AFFECTED_STATUSES = (AccountStatus.ASSIGNED.value, AccountStatus.POOL.value)


def _probe_tcp(host: str, port: int, timeout: float = _PROBE_TIMEOUT) -> bool:
    """Грубая проверка живости: удаётся ли установить TCP-соединение."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


async def check_proxies_impl(ctx: dict, *args: Any, **kwargs: Any) -> dict[str, list[int]]:
    now = ctx.get("now") or datetime.now(timezone.utc)
    prober: Callable[[Any], bool] = ctx.get("proxy_prober") or (
        lambda proxy: _probe_tcp(proxy.host, proxy.port)
    )
    session_factory = ctx["session_factory"]

    result: dict[str, list[int]] = {"alive": [], "dead": []}
    with session_factory() as session:
        proxies = ProxyRepository(session).list_all()
        for proxy in proxies:
            alive = bool(prober(proxy))
            ProxyRepository(session).update(
                proxy.id,
                ProxyUpdate(
                    status=ProxyStatus.ALIVE if alive else ProxyStatus.DEAD,
                    last_checked_at=now,
                ),
            )
            session.commit()
            if alive:
                result["alive"].append(proxy.id)
                continue

            result["dead"].append(proxy.id)
            affected = session.execute(
                select(Account.id).where(
                    Account.proxy_id == proxy.id,
                    Account.status.in_(_AFFECTED_STATUSES),
                )
            ).all()
            for (account_id,) in affected:
                HealthEventRepository(session).create(
                    HealthEventCreate(
                        account_id=account_id,
                        event_type=HealthEventType.PROXY_DOWN,
                        meta={"proxy_id": proxy.id},
                    )
                )
            session.commit()

    get_logger().info(
        "health.check_proxies.done",
        alive=len(result["alive"]),
        dead=len(result["dead"]),
    )
    return result
