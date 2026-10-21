"""Репозиторий задач парсинга (parsing.jobs) с живым прогрессом."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from modules.parsing.models.job import ParsingJob


class ParsingJobRepository:
    def __init__(self, session) -> None:
        self.session = session

    def create(
        self, *, owner_user_id: int, kind: str, name: str, params: dict
    ) -> ParsingJob:
        job = ParsingJob(
            owner_user_id=owner_user_id,
            kind=kind,
            name=name,
            params=params,
            status="pending",
            control="run",
            log=[],
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get(self, job_id: int) -> Optional[ParsingJob]:
        return self.session.get(ParsingJob, job_id)

    def list_by_owner(self, owner_user_id: int, limit: int = 20) -> list[ParsingJob]:
        stmt = (
            select(ParsingJob)
            .where(ParsingJob.owner_user_id == owner_user_id)
            .order_by(ParsingJob.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def append_log(self, job_id: int, message: str, *, max_lines: int = 500) -> None:
        job = self.get(job_id)
        if job is None:
            return
        line = {"ts": datetime.now(timezone.utc).isoformat(), "msg": message}
        # JSONB list — пересобираем, чтобы SQLAlchemy заметил изменение.
        job.log = ([*(job.log or []), line])[-max_lines:]
        self.session.flush()

    def set_counts(
        self, job_id: int, *, raw: Optional[int] = None, inserted: Optional[int] = None
    ) -> None:
        job = self.get(job_id)
        if job is None:
            return
        if raw is not None:
            job.raw_count = int(raw)
        if inserted is not None:
            job.inserted_count = int(inserted)
        self.session.flush()

    def set_status(self, job_id: int, status: str) -> None:
        job = self.get(job_id)
        if job is None:
            return
        job.status = status
        self.session.flush()

    def set_control(self, job_id: int, control: str) -> Optional[ParsingJob]:
        job = self.get(job_id)
        if job is None:
            return None
        job.control = control
        # Пауза/снятие паузы отражаем и в статусе, если задача ещё идёт.
        if control == "pause" and job.status == "running":
            job.status = "paused"
        elif control == "run" and job.status == "paused":
            job.status = "running"
        self.session.flush()
        return job

    def read_control(self, job_id: int) -> str:
        job = self.get(job_id)
        return job.control if job is not None else "stop"

    def finish(
        self,
        job_id: int,
        *,
        status: str,
        list_id: Optional[int] = None,
        raw: Optional[int] = None,
        inserted: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        job = self.get(job_id)
        if job is None:
            return
        job.status = status
        if list_id is not None:
            job.list_id = list_id
        if raw is not None:
            job.raw_count = int(raw)
        if inserted is not None:
            job.inserted_count = int(inserted)
        if error is not None:
            job.error = error[:2000]
        self.session.flush()
