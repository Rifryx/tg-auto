from datetime import datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.enums import LLMProvider
from core.schemas.base import ORMModel

PostSelectionMode = Literal["all", "keywords", "probability"]
PostScope = Literal["new", "existing", "mixed"]
WorkMode = Literal["by_count", "by_time_window"]
ChannelSourceMode = Literal["by_account_subscriptions", "explicit_links"]
OnNotSubscribedAction = Literal["subscribe_and_notify", "notify_only"]


class CampaignCreate(BaseModel):
    name: str
    # Легаси: каналы теперь живут на аккаунтах, кампания — просто папка. Поле
    # оставлено опциональным для обратной совместимости старого слушателя.
    target_channel: Optional[str] = None
    base_system_prompt: str
    llm_provider: LLMProvider
    active_hours_start: time
    active_hours_end: time
    active_hours_tz: str
    posting_delay_min_sec: int
    posting_delay_max_sec: int
    # Все *_delay/floodwait поля опциональны в Create — если не переданы,
    # берутся дефолты БД (соответствуют «Рекомендуемому» пресету).
    join_delay_min_sec: Optional[int] = None
    join_delay_max_sec: Optional[int] = None
    floodwait_pause_sec: Optional[int] = None
    floodwait_quarantine_max: Optional[int] = None
    discussion_group_id: Optional[int] = None
    persona_id: Optional[int] = None
    enabled: bool = True

    # ── Режимы отбора и работы (§ Этап 2) ──────────────────────────────
    post_selection_mode: PostSelectionMode = "all"
    keywords: list[str] = Field(default_factory=list)
    probability_percent: int = Field(default=100, ge=0, le=100)
    post_scope: PostScope = "new"
    work_mode: WorkMode = "by_count"
    max_comments: Optional[int] = Field(default=None, gt=0)
    min_words: int = Field(default=0, ge=0)
    window_after_post_sec: Optional[int] = Field(default=None, gt=0)
    pause_between_sec: Optional[int] = Field(default=None, ge=0)
    channel_source_mode: ChannelSourceMode = "explicit_links"
    on_not_subscribed_action: OnNotSubscribedAction = "notify_only"
    # Стиль комментариев (§ Этап 4)
    use_emojis: bool = True
    use_stickers: bool = False
    attach_image: bool = False
    write_as_channel: bool = False
    verify_after_post: bool = False
    verify_delay_sec: int = Field(default=300, gt=0)


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    target_channel: Optional[str] = None
    base_system_prompt: Optional[str] = None
    llm_provider: Optional[LLMProvider] = None
    active_hours_start: Optional[time] = None
    active_hours_end: Optional[time] = None
    active_hours_tz: Optional[str] = None
    posting_delay_min_sec: Optional[int] = None
    posting_delay_max_sec: Optional[int] = None
    join_delay_min_sec: Optional[int] = None
    join_delay_max_sec: Optional[int] = None
    floodwait_pause_sec: Optional[int] = None
    floodwait_quarantine_max: Optional[int] = None
    discussion_group_id: Optional[int] = None
    persona_id: Optional[int] = None
    enabled: Optional[bool] = None

    post_selection_mode: Optional[PostSelectionMode] = None
    keywords: Optional[list[str]] = None
    probability_percent: Optional[int] = Field(default=None, ge=0, le=100)
    post_scope: Optional[PostScope] = None
    work_mode: Optional[WorkMode] = None
    max_comments: Optional[int] = Field(default=None, gt=0)
    min_words: Optional[int] = Field(default=None, ge=0)
    window_after_post_sec: Optional[int] = Field(default=None, gt=0)
    pause_between_sec: Optional[int] = Field(default=None, ge=0)
    channel_source_mode: Optional[ChannelSourceMode] = None
    on_not_subscribed_action: Optional[OnNotSubscribedAction] = None
    use_emojis: Optional[bool] = None
    use_stickers: Optional[bool] = None
    attach_image: Optional[bool] = None
    write_as_channel: Optional[bool] = None
    verify_after_post: Optional[bool] = None
    verify_delay_sec: Optional[int] = Field(default=None, gt=0)


class CampaignRead(ORMModel):
    id: int
    owner_user_id: Optional[str]
    name: str
    target_channel: Optional[str]
    discussion_group_id: Optional[int]
    base_system_prompt: str
    persona_id: Optional[int]
    llm_provider: LLMProvider
    active_hours_start: time
    active_hours_end: time
    active_hours_tz: str
    posting_delay_min_sec: int
    posting_delay_max_sec: int
    join_delay_min_sec: int
    join_delay_max_sec: int
    floodwait_pause_sec: int
    floodwait_quarantine_max: int
    enabled: bool
    post_selection_mode: PostSelectionMode
    keywords: list[str]
    probability_percent: int
    post_scope: PostScope
    work_mode: WorkMode
    max_comments: Optional[int]
    min_words: int
    window_after_post_sec: Optional[int]
    pause_between_sec: Optional[int]
    channel_source_mode: ChannelSourceMode
    on_not_subscribed_action: OnNotSubscribedAction
    use_emojis: bool
    use_stickers: bool
    attach_image: bool
    write_as_channel: bool
    verify_after_post: bool
    verify_delay_sec: int
    created_at: datetime
    updated_at: datetime
