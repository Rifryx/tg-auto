from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from core.enums import HealthCategory, PhoneStatus
from core.schemas.base import ORMModel


class AccountHealthUpdate(BaseModel):
    """Партиальный апдейт snapshot'а — все поля опциональны."""

    health_score: Optional[int] = None
    score_computed_at: Optional[datetime] = None
    previous_score: Optional[int] = None
    session_alive: Optional[bool] = None
    last_seen_alive_at: Optional[datetime] = None
    last_session_check_at: Optional[datetime] = None
    spam_blocked: Optional[bool] = None
    spam_until: Optional[datetime] = None
    last_spam_check_at: Optional[datetime] = None
    phone_status: Optional[PhoneStatus] = None
    last_phone_check_at: Optional[datetime] = None
    has_2fa: Optional[bool] = None
    has_username: Optional[bool] = None
    has_avatar: Optional[bool] = None
    has_bio: Optional[bool] = None
    age_days: Optional[int] = None
    last_full_check_at: Optional[datetime] = None
    check_details: Optional[dict[str, Any]] = None


class AccountHealthRead(ORMModel):
    account_id: int
    health_score: int
    score_computed_at: Optional[datetime]
    previous_score: Optional[int]
    session_alive: Optional[bool]
    last_seen_alive_at: Optional[datetime]
    last_session_check_at: Optional[datetime]
    spam_blocked: Optional[bool]
    spam_until: Optional[datetime]
    last_spam_check_at: Optional[datetime]
    phone_status: PhoneStatus
    last_phone_check_at: Optional[datetime]
    has_2fa: Optional[bool]
    has_username: Optional[bool]
    has_avatar: Optional[bool]
    has_bio: Optional[bool]
    age_days: Optional[int]
    last_full_check_at: Optional[datetime]
    check_details: dict[str, Any]

    @property
    def category(self) -> HealthCategory:
        return HealthCategory.from_score(self.health_score)
