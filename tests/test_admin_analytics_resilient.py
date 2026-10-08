"""Аналитика админки не должна падать на недомигрированной БД.

Если таблицы (напр. ``payments`` из миграции 0054) ещё нет — запрос кидает
ProgrammingError и «портит» транзакцию. ``_safe`` обязан откатиться и отдать
дефолт, чтобы графики/статистика всё равно загрузились (а не 500).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.exc import ProgrammingError

from api.services import admin_analytics


def _programming_error():
    return ProgrammingError("SELECT 1", {}, Exception("relation does not exist"))


def test_safe_returns_default_and_rolls_back_on_programming_error():
    session = MagicMock()

    def boom():
        raise _programming_error()

    out = admin_analytics._safe(session, boom, {"ok": False})
    assert out == {"ok": False}
    session.rollback.assert_called_once()


def test_safe_passes_through_success():
    session = MagicMock()
    out = admin_analytics._safe(session, lambda: 42, 0)
    assert out == 42
    session.rollback.assert_not_called()


def test_get_timeseries_degrades_when_a_table_is_missing(monkeypatch):
    """payments-ряд недоступен → ряд из нулей, но ответ валиден и полон."""
    session = MagicMock()

    real_daily = admin_analytics._daily_counts

    def fake_daily(sess, col, since, *where):
        # Эмулируем отсутствие таблицы payments.
        if col is admin_analytics.Payment.paid_at:
            raise _programming_error()
        return {}

    monkeypatch.setattr(admin_analytics, "_daily_counts", fake_daily)
    assert real_daily is not fake_daily  # sanity

    out = admin_analytics.get_timeseries(session, days=3)
    assert out["days"] == 3
    assert len(out["series"]) == 3
    # Все дни присутствуют, payments обнулён, без исключения.
    assert all(row["payments"] == 0 for row in out["series"])
