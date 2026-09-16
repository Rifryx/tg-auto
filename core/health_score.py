"""Health Score v1: детерминированная формула на 0..100.

Принципы:
* Чистая функция от «фактов» — все побочки (fetch БД, telethon) остаются
  вызывающему коду. Легко юнит-тестируется.
* Прозрачная: каждая штрафная позиция возвращается в breakdown, чтобы UI мог
  объяснить «почему у аккаунта 47».
* Является базой под predictor (Этап 11). Когда появится ML, эта же формула
  останется как fallback и как baseline для сравнения.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


# ── Штрафные веса (единый источник правды) ────────────────────────────────────
FATAL_SESSION_DEAD = 100
FATAL_PHONE_BANNED = 100
PENALTY_SPAM_BLOCK = 60
PENALTY_PROXY_DEAD = 20
PENALTY_FLOOD_24H = 15
PENALTY_NO_2FA = 10
PENALTY_AGE_LT_3D = 10
PENALTY_NO_USERNAME = 5
PENALTY_NO_AVATAR = 5
PENALTY_NO_BIO = 3
PENALTY_PER_UNRESOLVED_INCIDENT = 10
PENALTY_UNRESOLVED_CAP = 30


@dataclass
class ScoreFacts:
    """Всё, что нужно знать формуле про аккаунт «прямо сейчас».

    Booleans допускают None ⇒ «неизвестно, штраф не применяется». Это важно:
    до первой пробы мы не должны наказывать аккаунт за то, что не проверили.
    """

    session_alive: Optional[bool] = None
    phone_banned: bool = False
    spam_blocked: bool = False
    proxy_dead: bool = False
    flood_wait_last_24h: bool = False
    has_2fa: Optional[bool] = None
    has_username: Optional[bool] = None
    has_avatar: Optional[bool] = None
    has_bio: Optional[bool] = None
    age_days: Optional[int] = None
    unresolved_incidents_last_24h: int = 0


@dataclass
class ScoreBreakdown:
    """Разложение итогового score по вкладам штрафов (для UI/debug)."""

    score: int
    reasons: list[tuple[str, int]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "reasons": [{"code": c, "penalty": p} for c, p in self.reasons],
        }


def compute_score(facts: ScoreFacts) -> ScoreBreakdown:
    """Вычисляет ``ScoreBreakdown`` из ``ScoreFacts``.

    Fatal-условия (session dead, phone banned) обнуляют score. Остальные штрафы
    суммируются и вычитаются из 100, результат зажимается в [0, 100].
    """
    reasons: list[tuple[str, int]] = []

    if facts.session_alive is False:
        reasons.append(("session_dead", FATAL_SESSION_DEAD))
        return ScoreBreakdown(score=0, reasons=reasons)
    if facts.phone_banned:
        reasons.append(("phone_banned", FATAL_PHONE_BANNED))
        return ScoreBreakdown(score=0, reasons=reasons)

    penalty = 0
    if facts.spam_blocked:
        reasons.append(("spam_block", PENALTY_SPAM_BLOCK))
        penalty += PENALTY_SPAM_BLOCK
    if facts.proxy_dead:
        reasons.append(("proxy_dead", PENALTY_PROXY_DEAD))
        penalty += PENALTY_PROXY_DEAD
    if facts.flood_wait_last_24h:
        reasons.append(("flood_wait_24h", PENALTY_FLOOD_24H))
        penalty += PENALTY_FLOOD_24H
    if facts.has_2fa is False:
        reasons.append(("no_2fa", PENALTY_NO_2FA))
        penalty += PENALTY_NO_2FA
    if facts.age_days is not None and facts.age_days < 3:
        reasons.append(("age_lt_3d", PENALTY_AGE_LT_3D))
        penalty += PENALTY_AGE_LT_3D
    if facts.has_username is False:
        reasons.append(("no_username", PENALTY_NO_USERNAME))
        penalty += PENALTY_NO_USERNAME
    if facts.has_avatar is False:
        reasons.append(("no_avatar", PENALTY_NO_AVATAR))
        penalty += PENALTY_NO_AVATAR
    if facts.has_bio is False:
        reasons.append(("no_bio", PENALTY_NO_BIO))
        penalty += PENALTY_NO_BIO

    incidents = max(0, facts.unresolved_incidents_last_24h)
    if incidents > 0:
        inc_pen = min(
            PENALTY_UNRESOLVED_CAP,
            incidents * PENALTY_PER_UNRESOLVED_INCIDENT,
        )
        reasons.append((f"unresolved_incidents_x{incidents}", inc_pen))
        penalty += inc_pen

    score = max(0, min(100, 100 - penalty))
    return ScoreBreakdown(score=score, reasons=reasons)


# ── Утилиты для построения ScoreFacts из «сырых» данных БД ────────────────────
def spam_blocked_now(spam_blocked: Optional[bool], spam_until: Optional[datetime],
                     now: Optional[datetime] = None) -> bool:
    """Активен ли спамблок сейчас (учитывая срок snapshot'а)."""
    if not spam_blocked:
        return False
    if spam_until is None:
        return True
    now = now or datetime.now(timezone.utc)
    return spam_until > now


def age_days_from(created_at: Optional[datetime],
                  now: Optional[datetime] = None) -> Optional[int]:
    if created_at is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, (now - created_at).days)


def flood_wait_recent(events_created_at: list[datetime],
                      now: Optional[datetime] = None) -> bool:
    """True, если среди событий есть flood_wait младше 24 часов."""
    if not events_created_at:
        return False
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    return any(ts >= cutoff for ts in events_created_at)
