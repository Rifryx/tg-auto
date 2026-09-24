"""Роутер модуля commenting (PROJECT-STAGES §1.2, §10).

Префикс ``/modules/commenting``. Смена статуса аккаунтов — только через
state machine (см. :mod:`modules.commenting.api.service`).

Монтирование (одной строкой в ``api/main.py``)::

    from modules.commenting.api import router as commenting_router
    app.include_router(commenting_router)
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.limits import enforce_limit
from api.deps.queue import get_publisher, get_task_queue
from core.enums import CommentStatus
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from modules.commenting.api import service
from modules.commenting.repositories import (
    AccountPresetRepository,
    CampaignAccountRepository,
    CampaignChannelRepository,
    CampaignRepository,
    ChannelBlacklistRepository,
    CommentLogRepository,
    DelayPresetRepository,
)
from modules.commenting.worker.registry import (
    ACTION_ATTACH,
    ACTION_DETACH,
    publish_campaign_lifecycle,
)
from modules.commenting.schemas.ai_protection import (
    AccountRiskBucket,
    AiProtectionFeature,
    AiProtectionStatus,
)
from modules.commenting.schemas.stats import (
    CampaignRuntimeSummary,
    CampaignStats,
)
from modules.commenting.schemas import (
    AccountPresetCreate,
    AccountPresetRead,
    AccountPresetUpdate,
    AttachAccountRequest,
    CampaignAccountRead,
    CampaignAccountUpdate,
    CampaignChannelBulkCreate,
    CampaignChannelCreate,
    CampaignChannelRead,
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    ChannelBlacklistCreate,
    ChannelAlertRead,
    ChannelBlacklistRead,
    CommentLogRead,
    DelayPresetCreate,
    DelayPresetRead,
    DelayPresetUpdate,
)

get_logger = structlog.get_logger

router = APIRouter(
    prefix="/modules/commenting",
    tags=["commenting"],
    dependencies=[Depends(require_user)],
)


# Поля кампании, после смены которых нужно пересобрать мониторинг каналов.
_CHANNEL_SYNC_FIELDS = {"enabled", "channel_source_mode", "on_not_subscribed_action"}


async def _request_backfill_existing(task_queue: TaskQueue, session: Session, campaign_id: int) -> None:
    """Прогуляться по истории каждого рабочего канала кампании (E2.1)."""
    from modules.commenting.models import MonitoredChannel

    rows = (
        session.query(MonitoredChannel.account_id, MonitoredChannel.id)
        .filter(
            MonitoredChannel.source_campaign_id == campaign_id,
            MonitoredChannel.status == "working",
        )
        .all()
    )
    for account_id, channel_id in rows:
        try:
            await task_queue.enqueue(
                TaskName.COMMENTING_BACKFILL_CHANNEL, account_id, channel_id
            )
        except Exception as exc:  # noqa: BLE001
            get_logger().warning(
                "commenting.backfill.enqueue_failed",
                campaign_id=campaign_id, channel_id=channel_id, error=repr(exc),
            )


async def _request_sync(task_queue: TaskQueue, campaign_id: int) -> None:
    """Поставить синхронизацию целевых каналов (E3.2). Мягко: синхронизация
    идемпотентна и перезапускается при следующей правке, поэтому недоступный
    Redis не должен ломать сам запрос пользователя."""
    try:
        await task_queue.enqueue(TaskName.COMMENTING_SYNC_CAMPAIGN_CHANNELS, campaign_id)
    except Exception as exc:  # noqa: BLE001
        get_logger().warning("commenting.sync.enqueue_failed", campaign_id=campaign_id, error=repr(exc))


def _drop_campaign_monitoring(session, publisher, campaign_id: int, account_id: Optional[int] = None,
                              input_ref: Optional[str] = None) -> None:
    from modules.commenting.models import MonitoredChannel
    from modules.commenting.worker.channels import ACTION_DETACH as CH_DETACH
    from modules.commenting.worker.channels import publish_channel_lifecycle

    q = session.query(MonitoredChannel).filter(MonitoredChannel.source_campaign_id == campaign_id)
    if account_id is not None:
        q = q.filter(MonitoredChannel.account_id == account_id)
    if input_ref is not None:
        q = q.filter(MonitoredChannel.input_ref == input_ref)
    rows = q.all()
    detach = [(r.account_id, r.id) for r in rows if r.status == "working"]
    for r in rows:
        session.delete(r)
    session.flush()
    for acc_id, ch_id in detach:
        publish_channel_lifecycle(publisher, acc_id, ch_id, CH_DETACH)


# --- Кампании (CRUD) ---------------------------------------------------------


@router.get("/campaigns", response_model=list[CampaignRead])
def list_campaigns(session: Session = Depends(get_session)) -> list[CampaignRead]:
    return [CampaignRead.model_validate(c) for c in CampaignRepository(session).list_all()]


@router.get("/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: int, session: Session = Depends(get_session)) -> CampaignRead:
    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    return CampaignRead.model_validate(campaign)


@router.post("/campaigns", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(
    body: CampaignCreate,
    session: Session = Depends(get_session),
    _limit: None = Depends(enforce_limit("campaigns_active_max")),
    user_id: str = Depends(require_user),
) -> CampaignRead:
    campaign = CampaignRepository(session).create(body)
    campaign.owner_user_id = user_id
    session.commit()
    return CampaignRead.model_validate(campaign)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignRead)
async def patch_campaign(
    campaign_id: int,
    body: CampaignUpdate,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> CampaignRead:
    campaign = CampaignRepository(session).update(campaign_id, body)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    session.commit()
    # Смена enabled → динамика слушателя (attach/detach) без рестарта воркера.
    # Публикуем ПОСЛЕ commit'а: изменение уже зафиксировано в БД (аудит #4).
    if body.enabled is not None:
        publish_campaign_lifecycle(
            publisher,
            campaign_id,
            ACTION_ATTACH if campaign.enabled else ACTION_DETACH,
        )
    if body.model_fields_set & _CHANNEL_SYNC_FIELDS:
        await _request_sync(task_queue, campaign_id)
    # Смена post_scope на existing/mixed: прогуляться по уже работающим
    # каналам кампании (E2.1). Первичное «existing» после создания кампании
    # цепляется сам через resolve_channel — здесь важен как раз PATCH.
    if "post_scope" in body.model_fields_set and body.post_scope in ("existing", "mixed"):
        await _request_backfill_existing(task_queue, session, campaign_id)
    return CampaignRead.model_validate(campaign)


@router.delete(
    "/campaigns/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> None:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    # detach публикуем ДО удаления записи: слушатель должен сняться раньше, чем
    # исчезнет кампания, иначе handler может сработать по уже удалённой кампании
    # (порядок, не гонка — acceptance #3).
    publish_campaign_lifecycle(publisher, campaign_id, ACTION_DETACH)
    # «Кампанийные» строки мониторинга удаляем явно: FK у них SET NULL, иначе
    # они стали бы ручными каналами аккаунтов и продолжили бы работать.
    _drop_campaign_monitoring(session, publisher, campaign_id)
    CampaignRepository(session).delete(campaign_id)
    session.commit()


# --- Аккаунты кампании (attach/detach) ---------------------------------------


@router.get("/campaigns/{campaign_id}/accounts", response_model=list[CampaignAccountRead])
def list_accounts(
    campaign_id: int, session: Session = Depends(get_session)
) -> list[CampaignAccountRead]:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
    return [CampaignAccountRead.model_validate(link) for link in links]


@router.post(
    "/campaigns/{campaign_id}/accounts",
    response_model=CampaignAccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def attach_account(
    campaign_id: int,
    body: AttachAccountRequest,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> CampaignAccountRead:
    try:
        link = service.attach_account(
            session,
            publisher,
            campaign_id,
            body.account_id,
            body.override_prompt,
            body.probability_override,
        )
    except service.CommentingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.CommentingConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    # Первый аккаунт enabled-кампании: раньше подключать было нечем (слушатель
    # писал "no_account" warning) — теперь триггерим attach (аудит #4).
    links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    if len(links) == 1 and campaign is not None and campaign.enabled:
        publish_campaign_lifecycle(publisher, campaign_id, ACTION_ATTACH)
    await _request_sync(task_queue, campaign_id)
    return CampaignAccountRead.model_validate(link)


@router.patch(
    "/campaigns/{campaign_id}/accounts/{account_id}",
    response_model=CampaignAccountRead,
)
def patch_campaign_account(
    campaign_id: int,
    account_id: int,
    body: CampaignAccountUpdate,
    session: Session = Depends(get_session),
) -> CampaignAccountRead:
    """Патч привязки (пока — probability_override, override_prompt).

    Используется для тумблера «Пер-аккаунтная вероятность» в UI при
    ``post_selection_mode='probability'``.
    """
    link = CampaignAccountRepository(session).update(campaign_id, account_id, body)
    if link is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"account {account_id} is not attached to campaign {campaign_id}",
        )
    session.commit()
    return CampaignAccountRead.model_validate(link)


@router.delete(
    "/campaigns/{campaign_id}/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def detach_account(
    campaign_id: int,
    account_id: int,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> None:
    try:
        service.detach_account(session, publisher, campaign_id, account_id)
    except service.CommentingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.CommentingConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await _request_sync(task_queue, campaign_id)


# --- Пресеты аккаунтов ------------------------------------------------------


@router.get("/presets/accounts", response_model=list[AccountPresetRead])
def list_account_presets(
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> list[AccountPresetRead]:
    presets = AccountPresetRepository(session).list_by_owner(user_id)
    return [AccountPresetRead.model_validate(p) for p in presets]


@router.post(
    "/presets/accounts",
    response_model=AccountPresetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_account_preset(
    body: AccountPresetCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> AccountPresetRead:
    preset = AccountPresetRepository(session).create(user_id, body)
    session.commit()
    return AccountPresetRead.model_validate(preset)


@router.patch("/presets/accounts/{preset_id}", response_model=AccountPresetRead)
def update_account_preset(
    preset_id: int,
    body: AccountPresetUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> AccountPresetRead:
    preset = AccountPresetRepository(session).update(preset_id, user_id, body)
    if preset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "preset not found")
    session.commit()
    return AccountPresetRead.model_validate(preset)


@router.delete(
    "/presets/accounts/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_account_preset(
    preset_id: int,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> None:
    if not AccountPresetRepository(session).delete(preset_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "preset not found")
    session.commit()


# --- Пресеты задержек -------------------------------------------------------


@router.get("/presets/delays", response_model=list[DelayPresetRead])
def list_delay_presets(
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> list[DelayPresetRead]:
    presets = DelayPresetRepository(session).list_visible(user_id)
    return [DelayPresetRead.model_validate(p) for p in presets]


@router.post(
    "/presets/delays",
    response_model=DelayPresetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_delay_preset(
    body: DelayPresetCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> DelayPresetRead:
    preset = DelayPresetRepository(session).create(user_id, body)
    session.commit()
    return DelayPresetRead.model_validate(preset)


@router.patch("/presets/delays/{preset_id}", response_model=DelayPresetRead)
def update_delay_preset(
    preset_id: int,
    body: DelayPresetUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> DelayPresetRead:
    preset = DelayPresetRepository(session).update(preset_id, user_id, body)
    if preset is None:
        # Может быть 404 (нет) или попытка редактировать системный (не own).
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "preset not found or not editable"
        )
    session.commit()
    return DelayPresetRead.model_validate(preset)


@router.delete(
    "/presets/delays/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_delay_preset(
    preset_id: int,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> None:
    if not DelayPresetRepository(session).delete(preset_id, user_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "preset not found or not deletable"
        )
    session.commit()


# --- Целевые каналы кампании (§ Этап 3) -------------------------------------


@router.get(
    "/campaigns/{campaign_id}/channels",
    response_model=list[CampaignChannelRead],
)
def list_campaign_channels(
    campaign_id: int, session: Session = Depends(get_session)
) -> list[CampaignChannelRead]:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    items = CampaignChannelRepository(session).list_by_campaign(campaign_id)
    return [CampaignChannelRead.model_validate(i) for i in items]


@router.post(
    "/campaigns/{campaign_id}/channels",
    response_model=list[CampaignChannelRead],
    status_code=status.HTTP_201_CREATED,
)
async def add_campaign_channels(
    campaign_id: int,
    body: CampaignChannelBulkCreate,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> list[CampaignChannelRead]:
    """Bulk-добавление: одна ссылка на строку, дубли пропускаются молча."""
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    repo = CampaignChannelRepository(session)
    existing = {c.raw_input for c in repo.list_by_campaign(campaign_id)}
    created: list[CampaignChannelRead] = []
    for raw in body.raw_inputs:
        cleaned = raw.strip()
        if not cleaned or cleaned in existing:
            continue
        item = repo.create(campaign_id, CampaignChannelCreate(raw_input=cleaned))
        existing.add(cleaned)
        created.append(CampaignChannelRead.model_validate(item))
    session.commit()
    if created:
        await _request_sync(task_queue, campaign_id)
    return created


@router.delete(
    "/campaigns/{campaign_id}/channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_campaign_channel(
    campaign_id: int,
    channel_id: int,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> None:
    from modules.commenting.models import CampaignChannel

    link = session.get(CampaignChannel, channel_id)
    if link is None or link.campaign_id != campaign_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    # Сразу снимаем мониторинг этой ссылки у аккаунтов кампании.
    _drop_campaign_monitoring(session, publisher, campaign_id, input_ref=link.raw_input)
    CampaignChannelRepository(session).delete(campaign_id, channel_id)
    session.commit()


# --- Черный список каналов (§ Этап 3) ---------------------------------------


@router.get(
    "/campaigns/{campaign_id}/blacklist",
    response_model=list[ChannelBlacklistRead],
)
def list_blacklist(
    campaign_id: int, session: Session = Depends(get_session)
) -> list[ChannelBlacklistRead]:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    items = ChannelBlacklistRepository(session).list_by_campaign(campaign_id)
    return [ChannelBlacklistRead.model_validate(i) for i in items]


@router.post(
    "/campaigns/{campaign_id}/blacklist",
    response_model=ChannelBlacklistRead,
    status_code=status.HTTP_201_CREATED,
)
def add_blacklist(
    campaign_id: int,
    body: ChannelBlacklistCreate,
    session: Session = Depends(get_session),
) -> ChannelBlacklistRead:
    """Ручное добавление в ЧС; воркер добавляет автоматически с ``auto=True``."""
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    from sqlalchemy.exc import IntegrityError

    try:
        # «-1001234567890» из клиентов Telegram → id канала как у Telethon.
        if body.chat_id is not None and str(body.chat_id).startswith("-100"):
            body = body.model_copy(update={"chat_id": int(str(body.chat_id)[4:])})
        if body.username:
            body = body.model_copy(update={"username": body.username.strip().lstrip("@")})
        entry = ChannelBlacklistRepository(session).create(campaign_id, body, auto=False)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "already blacklisted") from None
    return ChannelBlacklistRead.model_validate(entry)


@router.delete(
    "/campaigns/{campaign_id}/blacklist/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def remove_blacklist(
    campaign_id: int, entry_id: int, session: Session = Depends(get_session)
) -> None:
    if not ChannelBlacklistRepository(session).delete(campaign_id, entry_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blacklist entry not found")
    session.commit()


# --- ИИ-защита аккаунтов (§ Этап 5) -----------------------------------------


_AI_PROTECTION_FEATURES: list[AiProtectionFeature] = [
    AiProtectionFeature(
        key="behavior_analysis",
        label="ИИ анализ поведения",
        description=(
            "Anti-Ban Predictor раз в 15 минут пересчитывает риск для всех "
            "активных аккаунтов (задача health.predict_ban_risk_batch)."
        ),
        status="active",
    ),
    AiProtectionFeature(
        key="human_mimicry",
        label="Имитация человека",
        description=(
            "Warming maintenance каждые 5 минут поддерживает человекоподобное "
            "поведение (задача warming.maintenance_scheduler)."
        ),
        status="active",
    ),
    AiProtectionFeature(
        key="ban_shield",
        label="Защита от банов",
        description=(
            "Health-monitor + автопилот раз в 10 минут переводят рискующие "
            "аккаунты в cooldown/limited и снимают их с нагрузки."
        ),
        status="active",
    ),
    AiProtectionFeature(
        key="adaptive_delays",
        label="Адаптивные задержки",
        description=(
            "Задержки постинга берутся из delay-пресета кампании, а FloodWait "
            "автоматически уводит аккаунт в паузу (floodwait_pause_sec)."
        ),
        status="active",
    ),
]


@router.get("/ai-protection/status", response_model=AiProtectionStatus)
def get_ai_protection_status(
    session: Session = Depends(get_session),
) -> AiProtectionStatus:
    """Read-only статус защиты для всех аккаунтов текущего инстанса.

    Никаких paywall'ов: защита включена по факту — daemon'ы запущены как
    cron-задачи воркера. Тут только агрегат для UI-плашки.
    """
    from sqlalchemy import func, select
    from core.models.account import Account
    from core.models.ban_risk import BanRiskSnapshot

    total = session.execute(select(func.count()).select_from(Account)).scalar_one()
    rows = session.execute(
        select(BanRiskSnapshot.risk_level, func.count())
        .group_by(BanRiskSnapshot.risk_level)
    ).all()
    buckets = AccountRiskBucket()
    covered = 0
    for level, count in rows:
        covered += count
        setattr(buckets, level, count)
    buckets.unknown = max(0, total - covered)

    return AiProtectionStatus(
        active=True,
        features=_AI_PROTECTION_FEATURES,
        accounts_by_risk=buckets,
        total_accounts=total,
    )


# --- Картинки кампании (E4.1) ------------------------------------------------


class MediaLinkBody(BaseModel):
    media_asset_ids: list[int] = Field(default_factory=list, max_length=200)


class MediaLinkRead(BaseModel):
    campaign_id: int
    media_asset_ids: list[int]


@router.get("/campaigns/{campaign_id}/media", response_model=MediaLinkRead)
def list_campaign_media(
    campaign_id: int, session: Session = Depends(get_session)
) -> MediaLinkRead:
    from modules.commenting.models import CampaignMediaAsset

    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    ids = list(
        session.query(CampaignMediaAsset.media_asset_id)
        .filter(CampaignMediaAsset.campaign_id == campaign_id)
        .order_by(CampaignMediaAsset.created_at.asc())
    )
    return MediaLinkRead(campaign_id=campaign_id, media_asset_ids=[i for (i,) in ids])


@router.put("/campaigns/{campaign_id}/media", response_model=MediaLinkRead)
def set_campaign_media(
    campaign_id: int,
    body: MediaLinkBody,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> MediaLinkRead:
    """Приложить к кампании выбранные картинки владельца одной транзакцией."""
    from core.models.media_asset import MediaAsset
    from modules.commenting.models import CampaignMediaAsset

    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    ids = set(body.media_asset_ids)
    if ids:
        owned = set(
            session.execute(
                select(MediaAsset.id).where(
                    MediaAsset.id.in_(ids), MediaAsset.user_id == user_id
                )
            ).scalars()
        )
        missing = ids - owned
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Не найдено или не принадлежит вам: {sorted(missing)}",
            )
    session.query(CampaignMediaAsset).filter(
        CampaignMediaAsset.campaign_id == campaign_id
    ).delete()
    for aid in ids:
        session.add(CampaignMediaAsset(campaign_id=campaign_id, media_asset_id=aid))
    session.commit()
    return MediaLinkRead(campaign_id=campaign_id, media_asset_ids=sorted(ids))


# --- Алерты целевых каналов (E3.2) ------------------------------------------


@router.get("/campaigns/{campaign_id}/alerts", response_model=list[ChannelAlertRead])
def list_campaign_alerts(
    campaign_id: int,
    include_resolved: bool = False,
    session: Session = Depends(get_session),
) -> list[ChannelAlertRead]:
    from modules.commenting.models import ChannelAlert

    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    q = session.query(ChannelAlert).filter(ChannelAlert.campaign_id == campaign_id)
    if not include_resolved:
        q = q.filter(ChannelAlert.resolved.is_(False))
    rows = q.order_by(ChannelAlert.created_at.desc()).limit(200).all()
    return [ChannelAlertRead.model_validate(r) for r in rows]


@router.post("/alerts/{alert_id}/resolve", response_model=ChannelAlertRead)
def resolve_alert(alert_id: int, session: Session = Depends(get_session)) -> ChannelAlertRead:
    """«Скрыть» алерт (пользователь разобрался сам)."""
    from modules.commenting.models import ChannelAlert

    alert = session.get(ChannelAlert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
    alert.resolved = True
    session.commit()
    return ChannelAlertRead.model_validate(alert)


# --- Статистика + Runtime-сводка (§ Этап 6) ---------------------------------


@router.get("/campaigns/{campaign_id}/stats", response_model=CampaignStats)
def get_campaign_stats(
    campaign_id: int, session: Session = Depends(get_session)
) -> CampaignStats:
    """Агрегат CommentLog по статусам. Кампанию проверяем — 404 если её нет."""
    from sqlalchemy import func, select
    from modules.commenting.models import CommentLog

    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")

    rows = session.execute(
        select(CommentLog.status, func.count())
        .where(CommentLog.campaign_id == campaign_id)
        .group_by(CommentLog.status)
    ).all()
    counts = {"posted": 0, "failed": 0, "flagged": 0}
    for st, cnt in rows:
        if st in counts:
            counts[st] = cnt
    total = sum(counts.values())
    rate = (counts["posted"] * 100) // total if total > 0 else 0
    return CampaignStats(
        total=total,
        posted=counts["posted"],
        failed=counts["failed"],
        flagged=counts["flagged"],
        success_rate_percent=rate,
    )


@router.get(
    "/campaigns/{campaign_id}/runtime-summary",
    response_model=CampaignRuntimeSummary,
)
def get_campaign_runtime_summary(
    campaign_id: int, session: Session = Depends(get_session)
) -> CampaignRuntimeSummary:
    """Что показать в «блоке запуска»: аккаунты / каналы / лимиты."""
    from sqlalchemy import func, select
    from modules.commenting.models import CampaignAccount, CampaignChannel

    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    accounts_count = session.execute(
        select(func.count()).select_from(CampaignAccount).where(
            CampaignAccount.campaign_id == campaign_id
        )
    ).scalar_one()
    channels_count = session.execute(
        select(func.count()).select_from(CampaignChannel).where(
            CampaignChannel.campaign_id == campaign_id
        )
    ).scalar_one()
    return CampaignRuntimeSummary(
        accounts_count=accounts_count,
        channels_count=channels_count,
        max_interval_sec=campaign.posting_delay_max_sec,
        max_comments=campaign.max_comments,
        enabled=campaign.enabled,
    )


# --- Логи комментариев -------------------------------------------------------


@router.get("/campaigns/{campaign_id}/logs", response_model=list[CommentLogRead])
def list_logs(
    campaign_id: int,
    status_filter: Optional[CommentStatus] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[CommentLogRead]:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    logs = CommentLogRepository(session).list_by_campaign(
        campaign_id, status=status_filter, limit=limit, offset=offset
    )
    return [CommentLogRead.model_validate(log) for log in logs]
