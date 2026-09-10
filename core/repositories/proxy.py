from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from core.enums import ProxyStatus
from core.models import Proxy
from core.repositories.base import BaseRepository
from core.schemas.proxy import ProxyCreate, ProxyUpdate


class ProxyRepository(BaseRepository[Proxy]):
    model = Proxy

    def create(self, data: ProxyCreate) -> Proxy:
        proxy = Proxy(**data.model_dump())
        return self._add(proxy)

    def update(self, id_: int, data: ProxyUpdate) -> Optional[Proxy]:
        proxy = self.get(id_)
        if proxy is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(proxy, field, value)
        self.session.flush()
        return proxy

    def delete(self, id_: int) -> bool:
        proxy = self.get(id_)
        if proxy is None:
            return False
        self.session.delete(proxy)
        self.session.flush()
        return True

    def list_by_status(self, status: ProxyStatus) -> list[Proxy]:
        stmt = select(Proxy).where(Proxy.status == ProxyStatus(status).value)
        return list(self.session.execute(stmt).scalars().all())
