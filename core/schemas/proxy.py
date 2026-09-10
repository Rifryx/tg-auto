from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from core.enums import ProxyStatus, ProxyType
from core.schemas.base import ORMModel


class ProxyCreate(BaseModel):
    host: str
    port: int
    type: ProxyType
    login: Optional[str] = None
    password_enc: Optional[bytes] = None
    geo: Optional[str] = None


class ProxyUpdate(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    type: Optional[ProxyType] = None
    login: Optional[str] = None
    password_enc: Optional[bytes] = None
    geo: Optional[str] = None
    status: Optional[ProxyStatus] = None
    last_checked_at: Optional[datetime] = None


class ProxyRead(ORMModel):
    id: int
    host: str
    port: int
    login: Optional[str]
    password_enc: Optional[bytes]
    type: ProxyType
    geo: Optional[str]
    status: ProxyStatus
    last_checked_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
