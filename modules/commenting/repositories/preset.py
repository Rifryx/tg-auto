"""Репозитории пресетов (§ Этап 1).

Оба скоупятся по ``owner_user_id`` (Telegram id, строка). Для delay-пресетов
дополнительно доступна выборка системных (owner NULL, is_system=True).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.commenting.models.preset import AccountPreset, DelayPreset
from modules.commenting.schemas.preset import (
    AccountPresetCreate,
    AccountPresetUpdate,
    DelayPresetCreate,
    DelayPresetUpdate,
)


class AccountPresetRepository(BaseRepository[AccountPreset]):
    model = AccountPreset

    def list_by_owner(self, owner_user_id: str) -> list[AccountPreset]:
        stmt = (
            select(AccountPreset)
            .where(AccountPreset.owner_user_id == owner_user_id)
            .order_by(AccountPreset.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def get_owned(self, id_: int, owner_user_id: str) -> Optional[AccountPreset]:
        preset = self.get(id_)
        if preset is None or preset.owner_user_id != owner_user_id:
            return None
        return preset

    def create(self, owner_user_id: str, data: AccountPresetCreate) -> AccountPreset:
        preset = AccountPreset(
            owner_user_id=owner_user_id,
            name=data.name,
            account_ids=list(data.account_ids),
        )
        return self._add(preset)

    def update(
        self, id_: int, owner_user_id: str, data: AccountPresetUpdate
    ) -> Optional[AccountPreset]:
        preset = self.get_owned(id_, owner_user_id)
        if preset is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(preset, field, value)
        self.session.flush()
        return preset

    def delete(self, id_: int, owner_user_id: str) -> bool:
        preset = self.get_owned(id_, owner_user_id)
        if preset is None:
            return False
        self.session.delete(preset)
        self.session.flush()
        return True


class DelayPresetRepository(BaseRepository[DelayPreset]):
    model = DelayPreset

    def list_visible(self, owner_user_id: str) -> list[DelayPreset]:
        """Системные пресеты + пользовательские этого владельца."""
        stmt = (
            select(DelayPreset)
            .where(
                (DelayPreset.is_system.is_(True))
                | (DelayPreset.owner_user_id == owner_user_id)
            )
            .order_by(
                # системные сверху, затем свежие пользовательские
                DelayPreset.is_system.desc(),
                DelayPreset.created_at.desc(),
            )
        )
        return list(self.session.execute(stmt).scalars())

    def get_visible(self, id_: int, owner_user_id: str) -> Optional[DelayPreset]:
        preset = self.get(id_)
        if preset is None:
            return None
        if preset.is_system or preset.owner_user_id == owner_user_id:
            return preset
        return None

    def get_owned(self, id_: int, owner_user_id: str) -> Optional[DelayPreset]:
        preset = self.get(id_)
        # Системные редактировать нельзя — get_owned их не выдаёт.
        if preset is None or preset.is_system or preset.owner_user_id != owner_user_id:
            return None
        return preset

    def create(self, owner_user_id: str, data: DelayPresetCreate) -> DelayPreset:
        preset = DelayPreset(
            owner_user_id=owner_user_id,
            name=data.name,
            is_system=False,
            posting_delay_min_sec=data.posting_delay_min_sec,
            posting_delay_max_sec=data.posting_delay_max_sec,
            join_delay_min_sec=data.join_delay_min_sec,
            join_delay_max_sec=data.join_delay_max_sec,
            floodwait_pause_sec=data.floodwait_pause_sec,
            floodwait_quarantine_max=data.floodwait_quarantine_max,
        )
        return self._add(preset)

    def update(
        self, id_: int, owner_user_id: str, data: DelayPresetUpdate
    ) -> Optional[DelayPreset]:
        preset = self.get_owned(id_, owner_user_id)
        if preset is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(preset, field, value)
        self.session.flush()
        return preset

    def delete(self, id_: int, owner_user_id: str) -> bool:
        preset = self.get_owned(id_, owner_user_id)
        if preset is None:
            return False
        self.session.delete(preset)
        self.session.flush()
        return True
