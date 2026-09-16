"""Тела health-задач (PROJECT-STAGES §5.3, этап 4 УТП).

Cron/задачи:
* ``health.check_proxies`` (cron 10 мин): пингует прокси, обновляет
  ``proxies.status``/``last_checked_at``; для аккаунтов на мёртвом прокси в
  assigned/pool фиксирует ``HealthEvent(proxy_down)``, НЕ меняя статус аккаунта
  (решение оставляем пользователю).
* ``health.check_account`` (по требованию/из periodic): полный или частичный
  набор проб (session/profile/spamblock), обновление snapshot, пересчёт score,
  публикация ``health.snapshot_updated``.
* ``health.check_accounts_periodic`` (cron 3ч): выбирает батч аккаунтов и
  ставит для каждого ``health.check_account``. Частота для конкретного акка
  адаптивная — 12ч базово, 3ч для score<40. Спам-проба в периодическом пути
  НЕ включается (только по требованию/после incident).
* ``health.recompute_score``: пересчёт агрегата поверх текущих фактов
  (использует ``AccountHealth`` + ``HealthEvent`` + возраст/прокси). Дешёвая,
  вызывается после проб и точечно из API.
* ``health.cooldown_return`` реализована в worker/tasks/handlers.py (возврат из
  cooldown через state machine) — здесь не дублируется.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import select

from core.config import get_settings
from core.enums import AccountStatus, HealthEventType, PhoneStatus, ProxyStatus
from core.health_score import (
    ScoreFacts,
    age_days_from,
    compute_score,
    flood_wait_recent,
    spam_blocked_now,
)
from core.models import Account, AccountHealth, HealthEvent
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.repositories.account_health import AccountHealthRepository
from core.repositories.health_event import HealthEventRepository
from core.repositories.proxy import ProxyRepository
from core.schemas.account_health import AccountHealthUpdate
from core.schemas.health import HealthEventCreate
from core.schemas.proxy import ProxyUpdate
from worker.health.probes import probe_profile, probe_session, probe_spamblock
from worker.health.proxy_probe import probe_proxy
from worker.tasks.logging import get_logger

_AFFECTED_STATUSES = (AccountStatus.ASSIGNED.value, AccountStatus.POOL.value)
_PROBABLE_STATUSES = (
    AccountStatus.POOL.value,
    AccountStatus.ASSIGNED.value,
    AccountStatus.WARMING.value,
    AccountStatus.COOLDOWN.value,
)

# Канал pub/sub для live-обновлений health-snapshot в mini-app.
HEALTH_SNAPSHOT_CHANNEL = "health.snapshot_updated"

# Каденс автопроверок (этап 4, п.2 УТП: адаптивно).
_BASE_INTERVAL_HOURS = 12
_AT_RISK_INTERVAL_HOURS = 3
_AT_RISK_SCORE = 40


def _default_prober(ctx: dict) -> Callable[[Any], Any]:
    settings = get_settings()
    target = (settings.proxy_check_host, settings.proxy_check_port)
    return lambda proxy: probe_proxy(proxy, target=target)


# ── health.check_proxies (существующий) ──────────────────────────────────────
async def check_proxies_impl(ctx: dict, *args: Any, **kwargs: Any) -> dict[str, list[int]]:
    now = ctx.get("now") or datetime.now(timezone.utc)
    prober: Callable[[Any], Any] = ctx.get("proxy_prober") or _default_prober(ctx)
    session_factory = ctx["session_factory"]

    result: dict[str, list[int]] = {"alive": [], "dead": []}
    with session_factory() as session:
        proxies = ProxyRepository(session).list_all()
        for proxy in proxies:
            probed = prober(proxy)
            if inspect.isawaitable(probed):
                probed = await probed
            alive = bool(probed)
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


# ── health.check_account (all-in-one) ────────────────────────────────────────
async def check_account_impl(
    ctx: dict,
    account_id: int,
    probes: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Прогоняет пробы, обновляет snapshot, пересчитывает score, публикует событие.

    ``probes``: подмножество из ``["session", "profile", "spamblock"]``. По
    умолчанию — session+profile (spamblock только по явному запросу).
    """
    now = ctx.get("now") or datetime.now(timezone.utc)
    session_factory = ctx["session_factory"]
    publisher: Optional[Publisher] = ctx.get("publisher")
    client_pool = ctx["client_pool"]

    probe_set = set(probes or ["session", "profile"])

    # Клиент берём/освобождаем в обёртке try/finally, чтобы не текли ссылки.
    client = await client_pool.get(account_id)
    try:
        payload: dict[str, Any] = {}
        if "session" in probe_set:
            payload.update(await probe_session(
                client, account_id=account_id,
                session_factory=session_factory, publisher=publisher, now=now,
            ))
        # Если сессия уже мертва — профиль/спам-бот пробить не сможем, не тратим.
        session_dead = payload.get("session_alive") is False
        if not session_dead and "profile" in probe_set:
            payload.update(await probe_profile(
                client, account_id=account_id,
                session_factory=session_factory, publisher=publisher, now=now,
            ))
        if not session_dead and "spamblock" in probe_set:
            payload.update(await probe_spamblock(
                client, account_id=account_id,
                session_factory=session_factory, publisher=publisher, now=now,
            ))
    finally:
        await client_pool.release(account_id)

    payload["last_full_check_at"] = now
    _persist_snapshot(session_factory, account_id, payload)

    score = _recompute_and_publish(session_factory, publisher, account_id, now)
    get_logger().info(
        "health.check_account.done",
        account_id=account_id,
        probes=sorted(probe_set),
        score=score,
    )
    return {"account_id": account_id, "score": score, **payload}


# ── health.check_accounts_periodic (cron 3ч, адаптивно) ──────────────────────
async def check_accounts_periodic_impl(
    ctx: dict, *args: Any, **kwargs: Any
) -> dict[str, Any]:
    """Ставит ``health.check_account`` для аккаунтов, у которых пришло время.

    * ``score < 40`` → раз в 3ч (или если ни разу не проверяли);
    * иначе → раз в 12ч.

    Rate-limit ставится на уровне arq/очереди; здесь батчим через TaskQueue.
    """
    now = ctx.get("now") or datetime.now(timezone.utc)
    session_factory = ctx["session_factory"]
    queue = TaskQueue(redis=ctx.get("redis"))

    base_cutoff = now - timedelta(hours=_BASE_INTERVAL_HOURS)
    risk_cutoff = now - timedelta(hours=_AT_RISK_INTERVAL_HOURS)

    enqueued: list[int] = []
    with session_factory() as session:
        # LEFT JOIN, чтобы аккаунты без snapshot'а (созданы после миграции 0008)
        # тоже попадали в очередь — им и нужна первая полная проверка.
        stmt = (
            select(
                Account.id,
                AccountHealth.health_score,
                AccountHealth.last_full_check_at,
            )
            .outerjoin(AccountHealth, AccountHealth.account_id == Account.id)
            .where(Account.status.in_(_PROBABLE_STATUSES))
        )
        for account_id, score, last_check in session.execute(stmt).all():
            score_val = 100 if score is None else score
            cutoff = risk_cutoff if score_val < _AT_RISK_SCORE else base_cutoff
            if last_check is None or last_check < cutoff:
                enqueued.append(account_id)

    for aid in enqueued:
        await queue.enqueue(TaskName.HEALTH_CHECK_ACCOUNT, aid)

    get_logger().info(
        "health.check_accounts_periodic.done",
        enqueued=len(enqueued),
    )
    return {"enqueued": enqueued}


# ── health.recompute_score ───────────────────────────────────────────────────
async def recompute_score_impl(ctx: dict, account_id: int) -> int:
    """Пересчёт score без проб (использует то, что уже в БД)."""
    now = ctx.get("now") or datetime.now(timezone.utc)
    session_factory = ctx["session_factory"]
    publisher: Optional[Publisher] = ctx.get("publisher")
    return _recompute_and_publish(session_factory, publisher, account_id, now)


# ── Внутреннее ───────────────────────────────────────────────────────────────
def _persist_snapshot(session_factory, account_id: int, payload: dict[str, Any]) -> None:
    if not payload:
        return
    # Нормализуем phone_status (enum → строка) для валидации схемой.
    ps = payload.get("phone_status")
    if isinstance(ps, PhoneStatus):
        payload["phone_status"] = ps.value
    with session_factory() as session:
        AccountHealthRepository(session).update(
            account_id, AccountHealthUpdate(**payload)
        )
        session.commit()


def _recompute_and_publish(
    session_factory,
    publisher: Optional[Publisher],
    account_id: int,
    now: datetime,
) -> int:
    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None:
            return 0
        health = AccountHealthRepository(session).get_or_create(account_id)

        # Собираем факты для чистой формулы.
        events_24h = (
            session.execute(
                select(HealthEvent.event_type, HealthEvent.created_at, HealthEvent.resolved)
                .where(HealthEvent.account_id == account_id)
                .where(HealthEvent.created_at >= now - timedelta(hours=24))
            )
            .all()
        )
        flood_ts: list[datetime] = [
            ts for etype, ts, _ in events_24h if etype == HealthEventType.FLOOD_WAIT.value
        ]
        unresolved_24h = sum(1 for _et, _ts, resolved in events_24h if not resolved)

        proxy_dead = False
        if account.proxy_id is not None:
            proxy = ProxyRepository(session).get(account.proxy_id)
            proxy_dead = proxy is not None and proxy.status == ProxyStatus.DEAD.value

        facts = ScoreFacts(
            session_alive=health.session_alive,
            phone_banned=health.phone_status == PhoneStatus.BANNED.value,
            spam_blocked=spam_blocked_now(health.spam_blocked, health.spam_until, now=now),
            proxy_dead=proxy_dead,
            flood_wait_last_24h=flood_wait_recent(flood_ts, now=now),
            has_2fa=health.has_2fa,
            has_username=health.has_username,
            has_avatar=health.has_avatar,
            has_bio=health.has_bio,
            age_days=age_days_from(account.created_at, now=now),
            unresolved_incidents_last_24h=unresolved_24h,
        )
        breakdown = compute_score(facts)

        previous = health.health_score
        AccountHealthRepository(session).update(
            account_id,
            AccountHealthUpdate(
                health_score=breakdown.score,
                previous_score=previous,
                score_computed_at=now,
                age_days=facts.age_days,
                check_details={"reasons": [
                    {"code": c, "penalty": p} for c, p in breakdown.reasons
                ]},
            ),
        )
        session.commit()

    if publisher is not None:
        publisher.publish(
            HEALTH_SNAPSHOT_CHANNEL,
            {
                "account_id": account_id,
                "score": breakdown.score,
                "previous_score": previous,
                "computed_at": now.isoformat(),
            },
        )
    return breakdown.score
