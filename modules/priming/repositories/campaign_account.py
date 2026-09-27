"""Репозиторий campaign_accounts.

Ключевая операция — :meth:`acquire_next`: атомарный выбор следующего
свободного аккаунта-инициатора кампании. Реализована через
``SELECT … FOR UPDATE SKIP LOCKED`` — тот же паттерн, что и у
:meth:`CampaignTargetRepository.claim_next`. Advisory-lock тут не нужен:
запись сама блокирует себя через row-lock, а SKIP LOCKED пропускает уже
занятые записи для параллельных orchestrator-тиков.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import and_, or_, select

from core.repositories.base import BaseRepository
from modules.priming.models import PrimingCampaignAccount
from modules.priming.schemas.enums import PrimingAccountState


class CampaignAccountRepository(BaseRepository[PrimingCampaignAccount]):
    model = PrimingCampaignAccount

    def get_by_id(self, id_: int) -> Optional[PrimingCampaignAccount]:
        return self.get(id_)

    def list_by_campaign(
        self, campaign_id: int
    ) -> list[PrimingCampaignAccount]:
        stmt = (
            select(PrimingCampaignAccount)
            .where(PrimingCampaignAccount.campaign_id == campaign_id)
            .order_by(PrimingCampaignAccount.id.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: Mapping[str, Any]) -> PrimingCampaignAccount:
        obj = PrimingCampaignAccount(**dict(data))
        return self._add(obj)

    def update(
        self, id_: int, data: Mapping[str, Any]
    ) -> Optional[PrimingCampaignAccount]:
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

    # --- горячий путь orchestrator'а --------------------------------------
    def acquire_next(
        self,
        campaign_id: int,
        *,
        daily_limit: int,
        now: Optional[datetime] = None,
    ) -> Optional[PrimingCampaignAccount]:
        """Взять первого доступного аккаунта кампании и пометить working.

        Идёт через SELECT ... FOR UPDATE SKIP LOCKED, поэтому параллельные
        тики оркестратора никогда не выберут одну и ту же запись.
        Возвращает None, если пуст доступный пул (все в cooldown/quarantined
        или уже отработали дневной лимит).

        Замечание: обновляем ровно одну запись; commit'ит вызывающий
        (executor управляет транзакцией шире).
        """
        now = now or datetime.now(timezone.utc)
        stmt = (
            select(PrimingCampaignAccount)
            .where(
                PrimingCampaignAccount.campaign_id == campaign_id,
                PrimingCampaignAccount.state == PrimingAccountState.IDLE.value,
                PrimingCampaignAccount.primes_today < daily_limit,
                or_(
                    PrimingCampaignAccount.next_available_at.is_(None),
                    PrimingCampaignAccount.next_available_at <= now,
                ),
            )
            .order_by(PrimingCampaignAccount.last_prime_at.asc().nullsfirst())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        obj = self.session.execute(stmt).scalars().first()
        if obj is None:
            return None
        obj.state = PrimingAccountState.WORKING.value
        self.session.flush()
        return obj

    def release_after_prime(
        self,
        id_: int,
        *,
        outcome: str,
        now: Optional[datetime] = None,
        cooldown_seconds: Optional[int] = None,
        flood_wait_sec: Optional[int] = None,
    ) -> Optional[PrimingCampaignAccount]:
        """Освобождает аккаунт после попытки прайминга и обновляет счётчики.

        Правила ветвления по outcome живут в executor'е (промпт 2.2); здесь —
        безусловное обновление счётчиков.
        """
        obj = self.get(id_)
        if obj is None:
            return None
        now = now or datetime.now(timezone.utc)
        obj.last_prime_at = now
        obj.primes_total += 1
        # Успех обнуляет consecutive-счётчик флудвейтов.
        if outcome == "primed":
            obj.primes_today += 1
            obj.flood_waits_consecutive = 0
            obj.state = PrimingAccountState.IDLE.value
        elif outcome == "flood_wait":
            obj.flood_waits_consecutive += 1
            obj.flood_waits_total += 1
            obj.state = PrimingAccountState.COOLDOWN.value
            if flood_wait_sec is not None:
                obj.next_available_at = _add_seconds(now, flood_wait_sec)
        else:
            obj.state = PrimingAccountState.IDLE.value
            if cooldown_seconds:
                obj.next_available_at = _add_seconds(now, cooldown_seconds)
        self.session.flush()
        return obj

    def quarantine(self, id_: int) -> Optional[PrimingCampaignAccount]:
        return self.update(id_, {"state": PrimingAccountState.QUARANTINED.value})

    def reset_daily_counters(self, campaign_id: int) -> int:
        """Обнулить ``primes_today`` для всех аккаунтов кампании.

        Плановая задача суточного тика; возвращает число обновлённых строк.
        """
        from sqlalchemy import update

        stmt = (
            update(PrimingCampaignAccount)
            .where(PrimingCampaignAccount.campaign_id == campaign_id)
            .values(primes_today=0)
        )
        return self.session.execute(stmt).rowcount


def _add_seconds(when: datetime, seconds: int) -> datetime:
    from datetime import timedelta

    return when + timedelta(seconds=seconds)
