"""Юнит-тесты форматтеров notifier'а (этап 13b). Без Redis и без aiogram."""

from __future__ import annotations

from bot.notifier import _fmt_account_status, _fmt_autopilot, _fmt_ban_risk


# ── account_status ──────────────────────────────────────────────────────────


def test_ban_event_produces_message():
    text = _fmt_account_status({
        "account_id": 42,
        "from": "pool",
        "to": "banned",
        "initiator": "health",
    })
    assert text is not None
    assert "#42" in text
    assert "забанен" in text.lower()


def test_cooldown_event_produces_message():
    text = _fmt_account_status({
        "account_id": 7,
        "from": "assigned",
        "to": "cooldown",
        "initiator": "health",
    })
    assert text is not None
    assert "охлаждении" in text.lower()


def test_user_retire_is_not_notified():
    """User сам вывел акк — пуш не нужен, он про это и так знает."""
    text = _fmt_account_status({
        "account_id": 7,
        "from": "pool",
        "to": "retired",
        "initiator": "user",
    })
    assert text is None


def test_auto_retire_is_notified():
    """Автопилот вывел акк — уведомляем: user мог этого не ожидать."""
    text = _fmt_account_status({
        "account_id": 7,
        "from": "pool",
        "to": "retired",
        "initiator": "auto",
    })
    assert text is not None


def test_normal_transitions_ignored():
    """pool→assigned не приходит в пуши: обычное продовое событие."""
    assert _fmt_account_status({
        "account_id": 1,
        "from": "pool",
        "to": "assigned",
        "initiator": "user",
    }) is None


def test_ban_event_shows_username_and_phone_not_just_id():
    """Детали аккаунта (username/телефон) видны, а не только голый #id."""
    text = _fmt_account_status({
        "account_id": 64,
        "from": "pool",
        "to": "banned",
        "initiator": "health",
        "username": "cool_user",
        "phone": "+79990001122",
        "display_name": None,
    })
    assert text is not None
    assert "@cool_user" in text
    assert "+79990001122" in text
    assert "#64" in text


def test_cooldown_event_shows_reason_and_until_in_russian():
    """Причина (health.incident) и время окончания — по-русски и читаемо."""
    text = _fmt_account_status({
        "account_id": 7,
        "from": "assigned",
        "to": "cooldown",
        "initiator": "health",
        "reason": "health.incident",
        "phone": "+79991112233",
        "cooldown_until": "2026-10-22T23:40:00+00:00",
    })
    assert text is not None
    assert "flood" in text.lower() or "спам" in text.lower() or "бан прокси" in text.lower()
    assert "22.10 23:40" in text
    assert "В работе" in text  # from=assigned переведён на русский


def test_account_label_falls_back_to_bare_id_without_details():
    """Без username/телефона/имени — остаётся прежний #id (обратная совместимость)."""
    text = _fmt_account_status({
        "account_id": 42,
        "from": "pool",
        "to": "banned",
        "initiator": "health",
    })
    assert text is not None
    assert "#42" in text


# ── ban_risk ────────────────────────────────────────────────────────────────


def test_ban_risk_low_ignored():
    """Уровень low/medium в пуши не идёт."""
    assert _fmt_ban_risk({
        "account_id": 1,
        "risk_score": 0.15,
        "risk_level": "low",
        "previous_risk_score": 0.05,
    }) is None
    assert _fmt_ban_risk({
        "account_id": 1,
        "risk_score": 0.35,
        "risk_level": "medium",
        "previous_risk_score": 0.05,
    }) is None


def test_ban_risk_rising_to_high_is_notified():
    text = _fmt_ban_risk({
        "account_id": 1,
        "risk_score": 0.65,
        "risk_level": "high",
        "previous_risk_score": 0.4,
    })
    assert text is not None
    assert "риск" in text.lower()


def test_ban_risk_first_measurement_at_high_is_notified():
    """previous=None (первый расчёт), уровень уже high — шлём."""
    text = _fmt_ban_risk({
        "account_id": 1,
        "risk_score": 0.7,
        "risk_level": "high",
        "previous_risk_score": None,
    })
    assert text is not None


def test_ban_risk_stable_high_not_re_notified():
    """Уровень не растёт (был 0.7, стал 0.65) — не спамим."""
    assert _fmt_ban_risk({
        "account_id": 1,
        "risk_score": 0.65,
        "risk_level": "high",
        "previous_risk_score": 0.7,
    }) is None


# ── autopilot ───────────────────────────────────────────────────────────────


def test_autopilot_zero_executed_ignored():
    """Тик прошёл, но executed=0 — не шлём (обычный «тихий» тик)."""
    assert _fmt_autopilot({"planned": 5, "executed": 0, "by_type": {}}) is None


def test_autopilot_with_actions_notified():
    text = _fmt_autopilot({
        "planned": 3,
        "executed": 2,
        "by_type": {"start_warming": 1, "throttle": 1},
    })
    assert text is not None
    assert "2 действий" in text
