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
    max_words: Optional[int] = Field(default=None, gt=0)
    existing_scope_max_posts: int = Field(default=200, gt=0)
    existing_scope_max_age_days: Optional[int] = Field(default=None, gt=0)
    window_after_post_sec: Optional[int] = Field(default=None, gt=0)
    pause_between_sec: Optional[int] = Field(default=None, ge=0)
    channel_source_mode: ChannelSourceMode = "explicit_links"
    on_not_subscribed_action: OnNotSubscribedAction = "notify_only"
    # Стиль комментариев (§ Этап 4)
    use_emojis: bool = True
    use_stickers: bool = False
    sticker_chance_percent: int = Field(default=25, ge=0, le=100)
    attach_image: bool = False
    image_chance_percent: int = Field(default=40, ge=0, le=100)
    image_caption_enabled: bool = True
    write_as_channel: bool = False
    verify_after_post: bool = False
    verify_delay_sec: int = Field(default=300, gt=0)
    thread_simulation_enabled: bool = True

    # ── Нейрокомментинг: доп. режимы ────────────────────────────────────
    token_economy_enabled: bool = False
    scheduled_start_at: Optional[datetime] = None
    product_mention_enabled: bool = False
    product_name: Optional[str] = None
    product_url: Optional[str] = None
    product_mention_chance_percent: int = Field(default=20, ge=0, le=100)
    postbot_forward_enabled: bool = False
    postbot_username: Optional[str] = None
    postbot_message_ids: list[int] = Field(default_factory=list)
    captcha_solving_enabled: bool = False


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
    max_words: Optional[int] = Field(default=None, gt=0)
    existing_scope_max_posts: Optional[int] = Field(default=None, gt=0)
    existing_scope_max_age_days: Optional[int] = Field(default=None, gt=0)
    window_after_post_sec: Optional[int] = Field(default=None, gt=0)
    pause_between_sec: Optional[int] = Field(default=None, ge=0)
    channel_source_mode: Optional[ChannelSourceMode] = None
    on_not_subscribed_action: Optional[OnNotSubscribedAction] = None
    use_emojis: Optional[bool] = None
    use_stickers: Optional[bool] = None
    sticker_chance_percent: Optional[int] = Field(default=None, ge=0, le=100)
    attach_image: Optional[bool] = None
    image_chance_percent: Optional[int] = Field(default=None, ge=0, le=100)
    image_caption_enabled: Optional[bool] = None
    write_as_channel: Optional[bool] = None
    verify_after_post: Optional[bool] = None
    verify_delay_sec: Optional[int] = Field(default=None, gt=0)
    thread_simulation_enabled: Optional[bool] = None

    token_economy_enabled: Optional[bool] = None
    # Optional[datetime] = None и так различает «не передали» (exclude_unset)
    # от «явно очистили» (передали null) — отдельный флаг не нужен.
    scheduled_start_at: Optional[datetime] = None
    product_mention_enabled: Optional[bool] = None
    product_name: Optional[str] = None
    product_url: Optional[str] = None
    product_mention_chance_percent: Optional[int] = Field(default=None, ge=0, le=100)
    postbot_forward_enabled: Optional[bool] = None
    postbot_username: Optional[str] = None
    postbot_message_ids: Optional[list[int]] = None
    captcha_solving_enabled: Optional[bool] = None


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
    max_words: Optional[int]
    existing_scope_max_posts: int
    existing_scope_max_age_days: Optional[int]
    window_after_post_sec: Optional[int]
    pause_between_sec: Optional[int]
    channel_source_mode: ChannelSourceMode
    on_not_subscribed_action: OnNotSubscribedAction
    use_emojis: bool
    use_stickers: bool
    sticker_chance_percent: int
    attach_image: bool
    image_chance_percent: int
    image_caption_enabled: bool
    write_as_channel: bool
    verify_after_post: bool
    verify_delay_sec: int
    thread_simulation_enabled: bool
    token_economy_enabled: bool
    scheduled_start_at: Optional[datetime]
    product_mention_enabled: bool
    product_name: Optional[str]
    product_url: Optional[str]
    product_mention_chance_percent: int
    postbot_forward_enabled: bool
    postbot_username: Optional[str]
    postbot_message_ids: list[int]
    captcha_solving_enabled: bool
    created_at: datetime
    updated_at: datetime
