from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, update

from core.enums import BulkItemStatus, BulkJobStatus
from core.models import BulkJob, BulkJobItem
from core.repositories.base import BaseRepository


class BulkJobRepository(BaseRepository[BulkJob]):
    model = BulkJob

    def create(
        self,
        *,
        action_type: str,
        payload: dict[str, Any],
        initiator: str,
        account_ids: Iterable[int],
    ) -> BulkJob:
        account_ids = list(dict.fromkeys(account_ids))  # dedup, сохраняем порядок
        job = BulkJob(
            action_type=action_type,
            payload=payload,
            initiator=initiator,
            total_count=len(account_ids),
        )
        self.session.add(job)
        self.session.flush()
        for aid in account_ids:
            self.session.add(BulkJobItem(job_id=job.id, account_id=aid))
        self.session.flush()
        return job

    def list_items(self, job_id: int) -> list[BulkJobItem]:
        stmt = (
            select(BulkJobItem)
            .where(BulkJobItem.job_id == job_id)
            .order_by(BulkJobItem.id.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_pending_items(self, job_id: int) -> list[BulkJobItem]:
        stmt = (
            select(BulkJobItem)
            .where(BulkJobItem.job_id == job_id)
            .where(BulkJobItem.status == BulkItemStatus.PENDING.value)
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_failed_items(self, job_id: int) -> list[BulkJobItem]:
        stmt = (
            select(BulkJobItem)
            .where(BulkJobItem.job_id == job_id)
            .where(BulkJobItem.status == BulkItemStatus.FAILED.value)
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_item(self, item_id: int) -> Optional[BulkJobItem]:
        return self.session.get(BulkJobItem, item_id)

    def mark_running(self, job_id: int, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        job = self.get(job_id)
        if job is None or job.status != BulkJobStatus.QUEUED.value:
            return
        job.status = BulkJobStatus.RUNNING.value
        job.started_at = now
        self.session.flush()

    def cancel(self, job_id: int, now: Optional[datetime] = None) -> Optional[BulkJob]:
        now = now or datetime.now(timezone.utc)
        job = self.get(job_id)
        if job is None:
            return None
        if job.status in (BulkJobStatus.DONE.value, BulkJobStatus.CANCELLED.value):
            return job
        # Ставим CANCELLED только те item'ы, что ещё не были обработаны.
        self.session.execute(
            update(BulkJobItem)
            .where(BulkJobItem.job_id == job_id)
            .where(BulkJobItem.status == BulkItemStatus.PENDING.value)
            .values(status=BulkItemStatus.CANCELLED.value, finished_at=now)
        )
        job.status = BulkJobStatus.CANCELLED.value
        job.finished_at = now
        self.session.flush()
        return job

    def apply_item_result(
        self,
        item_id: int,
        *,
        status: BulkItemStatus,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> Optional[BulkJobItem]:
        item = self.get_item(item_id)
        if item is None:
            return None
        item.status = status.value
        item.error = error
        item.result = result
        if started_at is not None:
            item.started_at = started_at
        if finished_at is not None:
            item.finished_at = finished_at
        self.session.flush()
        return item

    def recompute_counters(self, job_id: int) -> Optional[BulkJob]:
        """Пересчитывает done/failed/skipped из item'ов и, если всё закрыто,
        закрывает job (``done`` или ``failed``)."""
        job = self.get(job_id)
        if job is None:
            return None
        items = self.list_items(job_id)
        done = failed = skipped = pending_or_running = 0
        for it in items:
            if it.status == BulkItemStatus.DONE.value:
                done += 1
            elif it.status == BulkItemStatus.FAILED.value:
                failed += 1
            elif it.status == BulkItemStatus.SKIPPED.value:
                skipped += 1
            elif it.status in (
                BulkItemStatus.PENDING.value,
                BulkItemStatus.RUNNING.value,
            ):
                pending_or_running += 1
        job.done_count = done
        job.failed_count = failed
        job.skipped_count = skipped
        if job.status == BulkJobStatus.CANCELLED.value:
            self.session.flush()
            return job
        if pending_or_running == 0:
            job.finished_at = datetime.now(timezone.utc)
            job.status = (
                BulkJobStatus.FAILED.value
                if failed > 0
                else BulkJobStatus.DONE.value
            )
        self.session.flush()
        return job

    def reset_failed_to_pending(self, job_id: int) -> int:
        """Возвращает failed-item'ы в pending для повторной попытки. Сбрасывает
        finished_at/error/result и, если job был в DONE/FAILED, переводит в
        RUNNING (dispatch подхватит их снова)."""
        job = self.get(job_id)
        if job is None:
            return 0
        result = self.session.execute(
            update(BulkJobItem)
            .where(BulkJobItem.job_id == job_id)
            .where(BulkJobItem.status == BulkItemStatus.FAILED.value)
            .values(
                status=BulkItemStatus.PENDING.value,
                error=None,
                result=None,
                started_at=None,
                finished_at=None,
            )
        )
        count = int(result.rowcount or 0)
        if count > 0:
            job.status = BulkJobStatus.QUEUED.value
            job.finished_at = None
            self.session.flush()
        return count
