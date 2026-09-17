from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from core.enums import AccountStatus, WarmingProfile
from core.schemas.base import ORMModel


class AccountCreate(BaseModel):
    phone: str
    session_enc: bytes
    # Фингерпринт — задаётся на стадии created и далее неизменен (инвариант §0.3).
    device_model: str
    system_version: str
    app_version: str
    lang_code: str
    system_lang_code: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    proxy_id: Optional[int] = None
    persona_id: Optional[int] = None
    warming_profile: WarmingProfile = WarmingProfile.MEDIUM


class AccountUpdate(BaseModel):
    """Изменяемые через репозиторий поля. `status` и поля state machine сюда
    не входят — статус меняется только через AccountStateMachine (инвариант §0.5)."""

    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    session_enc: Optional[bytes] = None
    proxy_id: Optional[int] = None
    persona_id: Optional[int] = None
    warming_profile: Optional[WarmingProfile] = None
    # Фингерпринт: репозиторий примет только пока аккаунт в статусе created.
    device_model: Optional[str] = None
    system_version: Optional[str] = None
    app_version: Optional[str] = None
    lang_code: Optional[str] = None
    system_lang_code: Optional[str] = None


class AccountRead(ORMModel):
    id: int
    phone: str
    first_name: Optional[str]
    last_name: Optional[str]
    username: Optional[str]
    bio: Optional[str]
    avatar_url: Optional[str]
    session_enc: bytes
    proxy_id: Optional[int]
    persona_id: Optional[int]
    status: AccountStatus
    previous_status: Optional[AccountStatus]
    assigned_container_type: Optional[str]
    assigned_container_id: Optional[int]
    warming_profile: WarmingProfile
    warming_started_at: Optional[datetime]
    activated_at: Optional[datetime]
    cooldown_until: Optional[datetime]
    device_model: str
    system_version: str
    app_version: str
    lang_code: str
    system_lang_code: str
    created_at: datetime
    updated_at: datetime
