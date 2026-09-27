"""Репозиторий целей кампании.

Ключевая операция — :meth:`claim_next`: атомарный переход
``pending → assigned`` под ``FOR UPDATE SKIP LOCKED`` (spec §7.3).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.priming.models import PrimingCampaignTarget
from modules.priming.schemas.enums import (
    TargetLastSeen,
    TargetStatus,
    can_target_status_transition,
)


class CampaignTargetRepository(BaseRepository[PrimingCampaignTarget]):
    model = PrimingCampaignTarget

    def get_by_id(self, id_: int) -> Optional[PrimingCampaignTarget]:
        return self.get(id_)

    def list_by_campaign(
        self,
        campaign_id: int,
        *,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[PrimingCampaignTarget]:
        stmt = (
            select(PrimingCampaignTarget)
            .where(PrimingCampaignTarget.campaign_id == campaign_id)
            .order_by(PrimingCampaignTarget.id.asc())
        )
        if status is not None:
            stmt = stmt.where(PrimingCampaignTarget.status == status)
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars())

    def count_by_status(self, campaign_id: int) -> dict[str, int]:
        """Гистограмма по статусам — для UI-дашборда кампании."""
        from sqlalchemy import func

        stmt = (
            select(PrimingCampaignTarget.status, func.count())
            .where(PrimingCampaignTarget.campaign_id == campaign_id)
            .group_by(PrimingCampaignTarget.status)
        )
        return {status: cnt for status, cnt in self.session.execute(stmt)}

    def create(self, data: Mapping[str, Any]) -> PrimingCampaignTarget:
        payload = dict(data)
        payload.setdefault("last_seen_bucket", TargetLastSeen.UNKNOWN.value)
        payload.setdefault("status", TargetStatus.PENDING.value)
        obj = PrimingCampaignTarget(**payload)
        return self._add(obj)

    def bulk_create(
        self, campaign_id: int, rows: list[Mapping[str, Any]]
    ) -> int:
        """Массовая вставка целей; возвращает число вставленных строк.

        Дубли по (campaign_id, tg_user_id) — на уровне unique-индекса; здесь
        применяем ``ON CONFLICT DO NOTHING``, чтобы импорт CSV не падал
        целиком из-за одного повторного пользователя.
        """
        if not rows:
            return 0
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        payload = []
        for row in rows:
            item = dict(row)
            item["campaign_id"] = campaign_id
            item.setdefault("last_seen_bucket", TargetLastSeen.UNKNOWN.value)
            item.setdefault("status", TargetStatus.PENDING.value)
            payload.append(item)
        stmt = pg_insert(PrimingCampaignTarget).values(payload)
        # ON CONFLICT привязываем к уникальному индексу
        # (campaign_id, tg_user_id); строки без tg_user_id всё равно вставятся.
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["campaign_id", "tg_user_id"],
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def update(
        self, id_: int, data: Mapping[str, Any]
    ) -> Optional[PrimingCampaignTarget]:
        obj = self.get(id_)
        if obj is None:
            return None
        for k, v in data.items():
            setattr(obj, k, v)
        self.session.flush()
        return obj

    def delete_hard(self, id_: int) -> bool:
        obj = self.get(id_)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True

    def transition_status(
        self,
        id_: int,
        *,
        next_status: TargetStatus | str,
    ) -> Optional[PrimingCampaignTarget]:
        """Смена статуса с проверкой разрешённых переходов (spec §4.3)."""
        target = self.get(id_)
        if target is None:
            return None
        current = TargetStatus(target.status)
        nxt = TargetStatus(next_status)
        if not can_target_status_transition(current, nxt):
            raise ValueError(
                f"forbidden target status transition {current} -> {nxt}"
            )
        target.status = nxt.value
        self.session.flush()
        return target

    # --- горячий путь orchestrator'а --------------------------------------
    def claim_next(
        self,
        campaign_id: int,
        account_id: int,
    ) -> Optional[PrimingCampaignTarget]:
        """Атомарно перевести первую pending-цель в assigned.

        SELECT ... FOR UPDATE SKIP LOCKED гарантирует, что параллельные
        тики никогда не заберут одну и ту же строку. Возвращает None, если
        цели закончились.
        """
        stmt = (
            select(PrimingCampaignTarget)
            .where(
                PrimingCampaignTarget.campaign_id == campaign_id,
                PrimingCampaignTarget.status == TargetStatus.PENDING.value,
            )
            .order_by(PrimingCampaignTarget.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        target = self.session.execute(stmt).scalars().first()
        if target is None:
            return None
        target.status = TargetStatus.ASSIGNED.value
        target.assigned_account_id = account_id
        target.attempts += 1
        self.session.flush()
        return target

    def mark_result(
        self,
        id_: int,
        *,
        outcome_status: TargetStatus | str,
        error_code: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Optional[PrimingCampaignTarget]:
        target = self.get(id_)
        if target is None:
            return None
        current = TargetStatus(target.status)
        nxt = TargetStatus(outcome_status)
        if not can_target_status_transition(current, nxt):
            raise ValueError(
                f"forbidden target status transition {current} -> {nxt}"
            )
        target.status = nxt.value
        target.last_error_code = error_code
        if nxt is TargetStatus.PRIMED:
            target.primed_at = now or datetime.now(timezone.utc)
        self.session.flush()
        return target
