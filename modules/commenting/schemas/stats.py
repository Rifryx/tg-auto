"""Агрегат статистики кампании для UI (§ Этап 6)."""

from __future__ import annotations

from pydantic import BaseModel


class CampaignStats(BaseModel):
    """Read-only агрегат по CommentLog.status для одной кампании."""

    total: int = 0
    posted: int = 0
    failed: int = 0
    flagged: int = 0
    success_rate_percent: int = 0  # 0..100, округлено вниз


class CampaignRuntimeSummary(BaseModel):
    """Read-only сводка для «блока запуска»: аккаунты/каналы/лимиты."""

    accounts_count: int
    channels_count: int
    max_interval_sec: int  # posting_delay_max_sec
    max_comments: int | None  # NULL = без лимита
    enabled: bool
