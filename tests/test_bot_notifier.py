"""Юнит-тесты форматтеров notifier'а (этап 13b). Без Redis и без aiogram."""

from __future__ import annotations

from bot.notifier import (
    _fmt_account_status,
    _fmt_autopilot,
    _fmt_ban_risk,
    _fmt_priming_alert,
)


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


# ── priming.alert (этап: чат-команды, инциденты прайминга) ────────────────────


def test_priming_autopause_privacy_notified():
    text = _fmt_priming_alert({
        "event": "autopause_privacy",
        "campaign_id": 12,
        "rate": 0.42,
    })
    assert text is not None
    assert "#12" in text
    assert "автопауз" in text.lower()


def test_priming_autopause_flood_notified():
    text = _fmt_priming_alert({
        "event": "autopause_flood",
        "campaign_id": 5,
        "rate": 0.3,
    })
    assert text is not None
    assert "#5" in text


def test_priming_autopause_without_rate_still_notified():
    """rate может отсутствовать — алерт всё равно формируется, без процента."""
    text = _fmt_priming_alert({"event": "autopause_flood", "campaign_id": 8})
    assert text is not None
    assert "#8" in text


def test_priming_quarantined_notified():
    text = _fmt_priming_alert({
        "event": "quarantined",
        "campaign_id": 5,
        "account_id": 77,
        "consecutive": 3,
    })
    assert text is not None
    assert "#77" in text
    assert "карантин" in text.lower()


def test_priming_unknown_event_ignored():
    assert _fmt_priming_alert({"event": "whatever", "campaign_id": 1}) is None


def test_priming_alert_keyboard_paused_has_resume():
    """Клавиатура под алертом автопаузы: есть Возобновить/Остановить/Открыть."""
    from bot.chat_actions import CB_PREFIX, alert_keyboard

    kb = alert_keyboard(9, paused=True)
    flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"{CB_PREFIX}:resume:9" in flat
    assert f"{CB_PREFIX}:stop:9" in flat
    assert f"{CB_PREFIX}:open:9" in flat


def test_priming_alert_keyboard_running_has_no_resume():
    """Для не-приостановленного инцидента (карантин) кнопки Возобновить нет."""
    from bot.chat_actions import CB_PREFIX, alert_keyboard

    kb = alert_keyboard(9, paused=False)
    flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"{CB_PREFIX}:resume:9" not in flat
    assert f"{CB_PREFIX}:stop:9" in flat
