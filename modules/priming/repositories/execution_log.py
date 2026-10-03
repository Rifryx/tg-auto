"""Репозиторий execution_log (append-only)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from sqlalchemy import func, or_, select

from core.repositories.base import BaseRepository
from modules.priming.models import PrimingExecutionLog


class ExecutionLogRepository(BaseRepository[PrimingExecutionLog]):
    model = PrimingExecutionLog

    def get_by_id(self, id_: int) -> Optional[PrimingExecutionLog]:
        return self.get(id_)

    def list_by_campaign(
        self,
        campaign_id: int,
        *,
        outcome: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 100,
        after_id: Optional[int] = None,
    ) -> list[PrimingExecutionLog]:
        """Keyset-пагинация по (started_at desc, id desc), фильтр по outcome
        опционален, ``q`` ищет по error_code / trigger_action.
        """
        # Сортируем по id DESC — id монотонно растёт (bigserial), это
        # прокси для started_at DESC и даёт консистентный keyset.
        stmt = (
            select(PrimingExecutionLog)
            .where(PrimingExecutionLog.campaign_id == campaign_id)
            .order_by(PrimingExecutionLog.id.desc())
            .limit(limit)
        )
        if outcome is not None:
            stmt = stmt.where(PrimingExecutionLog.outcome == outcome)
        if after_id is not None:
            stmt = stmt.where(PrimingExecutionLog.id < after_id)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(PrimingExecutionLog.error_code).like(like),
                    func.lower(PrimingExecutionLog.trigger_action).like(like),
                )
            )
        return list(self.session.execute(stmt).scalars())

    def iter_for_export(
        self,
        campaign_id: int,
        *,
        outcome: Optional[str] = None,
        q: Optional[str] = None,
        batch_size: int = 500,
    ) -> Iterator[PrimingExecutionLog]:
        """Итератор для стримингового CSV-экспорта: не грузит всё в память,
        keyset по id DESC.
        """
        after_id: Optional[int] = None
        while True:
            rows = self.list_by_campaign(
                campaign_id, outcome=outcome, q=q,
                limit=batch_size, after_id=after_id,
            )
            if not rows:
                return
            for row in rows:
                yield row
            after_id = rows[-1].id
            if len(rows) < batch_size:
                return

    def append(
        self,
        *,
        campaign_id: int,
        account_id: int,
        target_id: int,
        started_at: datetime,
        finished_at: datetime,
        outcome: str,
        trigger_action: str,
        latency_ms: int,
        error_code: Optional[str] = None,
        flood_wait_sec: Optional[int] = None,
        dry_run: bool = False,
    ) -> PrimingExecutionLog:
        """Append-only вставка одной записи о попытке прайминга."""
        obj = PrimingExecutionLog(
            campaign_id=campaign_id,
            account_id=account_id,
            target_id=target_id,
            started_at=started_at,
            finished_at=finished_at,
            outcome=outcome,
            trigger_action=trigger_action,
            latency_ms=latency_ms,
            error_code=error_code,
            flood_wait_sec=flood_wait_sec,
            dry_run=dry_run,
        )
        return self._add(obj)

    def recent_outcomes(
        self, campaign_id: int, *, window: int = 200
    ) -> list[str]:
        """Последние N outcome'ов кампании — вход для расчёта privacy_rate.

        Возвращает список строк outcome в порядке от новых к старым.
        """
        stmt = (
            select(PrimingExecutionLog.outcome)
            .where(PrimingExecutionLog.campaign_id == campaign_id)
            .order_by(PrimingExecutionLog.id.desc())
            .limit(window)
        )
        return [row[0] for row in self.session.execute(stmt)]

    def outcome_counts(
        self,
        campaign_id: int,
        *,
        since: Optional[datetime] = None,
    ) -> dict[str, int]:
        """Суммарные счётчики по outcome (для мини-KPI экрана «Ход»)."""
        stmt = (
            select(
                PrimingExecutionLog.outcome,
                func.count(PrimingExecutionLog.id),
            )
            .where(PrimingExecutionLog.campaign_id == campaign_id)
            .group_by(PrimingExecutionLog.outcome)
        )
        if since is not None:
            stmt = stmt.where(PrimingExecutionLog.finished_at >= since)
        return {row[0]: int(row[1]) for row in self.session.execute(stmt)}

    def daily_health_buckets(
        self,
        account_id: int,
        *,
        days: int = 7,
        now: Optional[datetime] = None,
    ) -> list[dict[str, int]]:
        """7 (или ``days``) точек — по дням, для health-sparkline аккаунта.

        Возвращает список от старого дня к новому длиной ``days``,
        каждый элемент — {successes, floods, privacy}. День −0 —
        сегодня, −(days-1) — самый старый.
        """
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(days=days)
        stmt = (
            select(
                PrimingExecutionLog.finished_at,
                PrimingExecutionLog.outcome,
            )
            .where(
                PrimingExecutionLog.account_id == account_id,
                PrimingExecutionLog.finished_at >= since,
            )
        )
        buckets: list[dict[str, int]] = [
            {"successes": 0, "floods": 0, "privacy": 0} for _ in range(days)
        ]
        for finished_at, outcome in self.session.execute(stmt):
            if finished_at is None:
                continue
            if finished_at.tzinfo is None:
                finished_at = finished_at.replace(tzinfo=timezone.utc)
            delta_days = int((finished_at - since).total_seconds() // 86400)
            if not (0 <= delta_days < days):
                continue
            if outcome == "primed":
                buckets[delta_days]["successes"] += 1
            elif outcome == "flood_wait":
                buckets[delta_days]["floods"] += 1
            elif outcome == "privacy_restricted":
                buckets[delta_days]["privacy"] += 1
        return buckets

    def hourly_buckets(
        self,
        campaign_id: int,
        *,
        hours: int = 24,
        now: Optional[datetime] = None,
    ) -> list[int]:
        """Кол-во попыток по часам за последние ``hours`` — для sparkline.

        Возвращает список длиной ``hours``, элемент 0 — самый старый час,
        элемент -1 — текущий (даже если пустой).
        """
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)
        stmt = (
            select(PrimingExecutionLog.finished_at)
            .where(
                PrimingExecutionLog.campaign_id == campaign_id,
                PrimingExecutionLog.finished_at >= since,
            )
        )
        buckets = [0] * hours
        for (finished_at,) in self.session.execute(stmt):
            if finished_at is None:
                continue
            if finished_at.tzinfo is None:
                finished_at = finished_at.replace(tzinfo=timezone.utc)
            delta_hours = int((finished_at - since).total_seconds() // 3600)
            if 0 <= delta_hours < hours:
                buckets[delta_hours] += 1
        return buckets
