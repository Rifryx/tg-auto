"""Юнит-тесты чистой формулы Health Score (этап 4 УТП).

Без БД, без сети — тестируем только ``core.health_score``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.enums import HealthCategory
from core.health_score import (
    ScoreFacts,
    age_days_from,
    compute_score,
    flood_wait_recent,
    spam_blocked_now,
)


NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


# --- fatal-условия ------------------------------------------------------------


def test_session_dead_zeroes_score():
    b = compute_score(ScoreFacts(session_alive=False))
    assert b.score == 0
    assert ("session_dead", 100) in b.reasons


def test_phone_banned_zeroes_score():
    b = compute_score(ScoreFacts(session_alive=True, phone_banned=True))
    assert b.score == 0
    assert ("phone_banned", 100) in b.reasons


def test_fatal_short_circuits_other_penalties():
    b = compute_score(ScoreFacts(session_alive=False, spam_blocked=True, proxy_dead=True))
    assert b.score == 0
    # только fatal причина, штрафы не суммируются:
    assert b.reasons == [("session_dead", 100)]


# --- обычные штрафы -----------------------------------------------------------


def test_unknown_facts_produce_max_score():
    b = compute_score(ScoreFacts())
    assert b.score == 100
    assert b.reasons == []


def test_spam_block_penalty():
    b = compute_score(ScoreFacts(session_alive=True, spam_blocked=True))
    assert b.score == 40


def test_proxy_dead_penalty():
    b = compute_score(ScoreFacts(session_alive=True, proxy_dead=True))
    assert b.score == 80


def test_cosmetic_penalties_stack():
    # no_2fa(10) + no_username(5) + no_avatar(5) + no_bio(3) + age_lt_3d(10) = 33
    b = compute_score(
        ScoreFacts(
            session_alive=True,
            has_2fa=False,
            has_username=False,
            has_avatar=False,
            has_bio=False,
            age_days=1,
        )
    )
    assert b.score == 67


def test_unresolved_incidents_capped():
    # cap = 30 (не 100).
    b = compute_score(ScoreFacts(session_alive=True, unresolved_incidents_last_24h=10))
    assert b.score == 70


def test_flood_wait_penalty():
    b = compute_score(ScoreFacts(session_alive=True, flood_wait_last_24h=True))
    assert b.score == 85


def test_score_clamped_to_zero():
    # 60 + 20 + 15 + 10 + 5 + 5 + 3 + 30 (cap) = 148 → clamp 0.
    b = compute_score(
        ScoreFacts(
            session_alive=True,
            spam_blocked=True,
            proxy_dead=True,
            flood_wait_last_24h=True,
            has_2fa=False,
            has_username=False,
            has_avatar=False,
            has_bio=False,
            unresolved_incidents_last_24h=10,
        )
    )
    assert b.score == 0


def test_no_penalty_when_feature_unknown():
    # None → неизвестно → штраф не применяется.
    b = compute_score(ScoreFacts(session_alive=True, has_2fa=None, has_username=None))
    assert b.score == 100


def test_age_gte_3_days_no_penalty():
    b = compute_score(ScoreFacts(session_alive=True, age_days=3))
    assert b.score == 100


# --- утилиты ------------------------------------------------------------------


def test_spam_blocked_now_false_when_flag_false():
    assert spam_blocked_now(False, None, now=NOW) is False


def test_spam_blocked_now_true_when_no_until():
    assert spam_blocked_now(True, None, now=NOW) is True


def test_spam_blocked_now_expired():
    past = NOW - timedelta(hours=1)
    assert spam_blocked_now(True, past, now=NOW) is False


def test_spam_blocked_now_still_active():
    future = NOW + timedelta(hours=1)
    assert spam_blocked_now(True, future, now=NOW) is True


def test_age_days_from_none():
    assert age_days_from(None) is None


def test_age_days_from_past():
    created = NOW - timedelta(days=10, hours=3)
    assert age_days_from(created, now=NOW) == 10


def test_flood_wait_recent_true():
    ts = [NOW - timedelta(hours=1)]
    assert flood_wait_recent(ts, now=NOW) is True


def test_flood_wait_recent_false_when_old():
    ts = [NOW - timedelta(hours=48)]
    assert flood_wait_recent(ts, now=NOW) is False


def test_flood_wait_recent_empty():
    assert flood_wait_recent([], now=NOW) is False


# --- категории для UI ---------------------------------------------------------


def test_category_boundaries():
    assert HealthCategory.from_score(0) is HealthCategory.CRITICAL
    assert HealthCategory.from_score(1) is HealthCategory.RISKY
    assert HealthCategory.from_score(40) is HealthCategory.RISKY
    assert HealthCategory.from_score(41) is HealthCategory.WARM
    assert HealthCategory.from_score(70) is HealthCategory.WARM
    assert HealthCategory.from_score(71) is HealthCategory.HEALTHY
    assert HealthCategory.from_score(100) is HealthCategory.HEALTHY


def test_breakdown_serialization():
    b = compute_score(ScoreFacts(session_alive=True, spam_blocked=True))
    d = b.as_dict()
    assert d["score"] == 40
    assert {"code": "spam_block", "penalty": 60} in d["reasons"]
