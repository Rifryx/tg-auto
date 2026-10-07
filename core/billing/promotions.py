"""Акции: CRUD для админки + выдача/скрытие «шторки» пользователю.

Детерминизм «одна акция в момент времени» держится на валидации при записи:
нельзя включить акцию, чьё окно пересекается с окном другой ВКЛЮЧЁННОЙ акции.
Выключенные (``enabled=false``) в пересечении не участвуют — их можно готовить
заранее. Расчёт эффективной цены — в :mod:`core.billing.pricing`.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.promo_dismissal import PromoDismissal
from core.models.promotion import PROMO_BADGE_VARIANTS, Promotion


class PromotionValidationError(ValueError):
    """Некорректные поля акции или пересечение активных окон."""


def _validate_fields(
    *,
    kind: str,
    percent_off: Optional[int],
    promo_price_usdt: Optional[Decimal],
    promo_price_stars: Optional[int],
    badge_variant: str,
    starts_at: datetime,
    ends_at: datetime,
) -> None:
    if kind not in ("percent", "fixed"):
        raise PromotionValidationError("kind must be 'percent' or 'fixed'")
    if badge_variant not in PROMO_BADGE_VARIANTS:
        raise PromotionValidationError(
            f"badge_variant must be one of {PROMO_BADGE_VARIANTS}"
        )
    if ends_at <= starts_at:
        raise PromotionValidationError("ends_at must be after starts_at")
    if kind == "percent":
        if percent_off is None or not (1 <= percent_off <= 95):
            raise PromotionValidationError("percent_off must be in 1..95")
    else:  # fixed
        if promo_price_usdt is None or promo_price_stars is None:
            raise PromotionValidationError(
                "fixed promo requires promo_price_usdt and promo_price_stars"
            )
        if promo_price_usdt < 0 or promo_price_stars < 0:
            raise PromotionValidationError("promo prices must be non-negative")


def _assert_no_overlap(
    session: Session,
    *,
    starts_at: datetime,
    ends_at: datetime,
    exclude_id: Optional[int] = None,
) -> None:
    """Запретить пересечение с другой ВКЛЮЧЁННОЙ акцией."""
    stmt = select(Promotion).where(
        Promotion.enabled.is_(True),
        Promotion.starts_at < ends_at,
        Promotion.ends_at > starts_at,
    )
    if exclude_id is not None:
        stmt = stmt.where(Promotion.id != exclude_id)
    clash = session.execute(stmt.limit(1)).scalars().first()
    if clash is not None:
        raise PromotionValidationError(
            f"overlaps with enabled promotion #{clash.id} ({clash.title})"
        )


def list_promotions(session: Session) -> list[Promotion]:
    return list(
        session.execute(
            select(Promotion).order_by(Promotion.starts_at.desc())
        ).scalars()
    )


def create_promotion(
    session: Session,
    *,
    title: str,
    description: Optional[str],
    kind: str,
    percent_off: Optional[int],
    promo_price_usdt: Optional[Decimal],
    promo_price_stars: Optional[int],
    badge_variant: str,
    starts_at: datetime,
    ends_at: datetime,
    enabled: bool,
    created_by: Optional[str],
) -> Promotion:
    _validate_fields(
        kind=kind,
        percent_off=percent_off,
        promo_price_usdt=promo_price_usdt,
        promo_price_stars=promo_price_stars,
        badge_variant=badge_variant,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    if enabled:
        _assert_no_overlap(session, starts_at=starts_at, ends_at=ends_at)
    promo = Promotion(
        title=title,
        description=description,
        kind=kind,
        percent_off=percent_off,
        promo_price_usdt=promo_price_usdt,
        promo_price_stars=promo_price_stars,
        badge_variant=badge_variant,
        starts_at=starts_at,
        ends_at=ends_at,
        enabled=enabled,
        created_by=created_by,
    )
    session.add(promo)
    session.commit()
    session.refresh(promo)
    return promo


def update_promotion(
    session: Session, promo_id: int, *, fields: dict[str, object]
) -> Optional[Promotion]:
    promo = session.get(Promotion, promo_id)
    if promo is None:
        return None
    merged = {
        "kind": promo.kind,
        "percent_off": promo.percent_off,
        "promo_price_usdt": promo.promo_price_usdt,
        "promo_price_stars": promo.promo_price_stars,
        "badge_variant": promo.badge_variant,
        "starts_at": promo.starts_at,
        "ends_at": promo.ends_at,
        "enabled": promo.enabled,
    }
    merged.update({k: v for k, v in fields.items() if v is not None})
    _validate_fields(
        kind=str(merged["kind"]),
        percent_off=merged["percent_off"],  # type: ignore[arg-type]
        promo_price_usdt=merged["promo_price_usdt"],  # type: ignore[arg-type]
        promo_price_stars=merged["promo_price_stars"],  # type: ignore[arg-type]
        badge_variant=str(merged["badge_variant"]),
        starts_at=merged["starts_at"],  # type: ignore[arg-type]
        ends_at=merged["ends_at"],  # type: ignore[arg-type]
    )
    if merged["enabled"]:
        _assert_no_overlap(
            session,
            starts_at=merged["starts_at"],  # type: ignore[arg-type]
            ends_at=merged["ends_at"],  # type: ignore[arg-type]
            exclude_id=promo_id,
        )
    for key, value in merged.items():
        setattr(promo, key, value)
    # title/description — простые строки, применяем отдельно (могут обнуляться).
    if "title" in fields and fields["title"] is not None:
        promo.title = str(fields["title"])
    if "description" in fields:
        promo.description = fields["description"]  # type: ignore[assignment]
    session.commit()
    session.refresh(promo)
    return promo


def delete_promotion(session: Session, promo_id: int) -> bool:
    promo = session.get(Promotion, promo_id)
    if promo is None:
        return False
    session.delete(promo)
    session.commit()
    return True


def get_promo_for_user(session: Session, user_id: str) -> Optional[Promotion]:
    """Активная акция для пользователя, если он её ещё не скрыл."""
    from core.billing.pricing import get_active_promo

    promo = get_active_promo(session)
    if promo is None:
        return None
    dismissed = session.get(PromoDismissal, (user_id, promo.id))
    return None if dismissed is not None else promo


def dismiss_promo(session: Session, user_id: str, promo_id: int) -> None:
    """Записать скрытие шторки (идемпотентно)."""
    if session.get(PromoDismissal, (user_id, promo_id)) is not None:
        return
    session.add(PromoDismissal(user_id=user_id, promo_id=promo_id))
    session.commit()
