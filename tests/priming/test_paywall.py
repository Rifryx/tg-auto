"""Пейволл модуля прайминга (prompt 7.7).

Проверяем контракт FeatureKey + require_feature:
- ``priming_enabled`` присутствует в PLANS,
- на free — False, на pro — True,
- ``require_feature`` пропускает GET и валит POST/PATCH/DELETE 402.
"""

from __future__ import annotations

import pytest

from core.billing.plans import FEATURE_KEYS, PLANS, get_plan_limit


def test_priming_enabled_registered_in_plans() -> None:
    assert "priming_enabled" in FEATURE_KEYS
    assert get_plan_limit("free", "priming_enabled") is False
    assert get_plan_limit("pro", "priming_enabled") is True


def test_all_plans_contain_priming_enabled_key() -> None:
    for plan_id, limits in PLANS.items():
        assert "priming_enabled" in limits, plan_id


class _FakeRequest:
    def __init__(self, method: str) -> None:
        self.method = method


class _FakeBillingModule:
    """Мини-стенд, вместо реального billing_service."""

    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id

    def get_user_plan(self, session, user_id):
        return self.plan_id


def _dep(feature: str, plan_id: str, method: str):
    """Вызов require_feature('priming_enabled') без FastAPI-стека."""
    fastapi = pytest.importorskip("fastapi")
    from api.deps import limits as limits_mod

    fake = _FakeBillingModule(plan_id)
    orig = limits_mod.billing_service
    limits_mod.billing_service = fake  # type: ignore[assignment]
    try:
        dep = limits_mod.require_feature(feature)  # type: ignore[arg-type]
        try:
            dep(request=_FakeRequest(method), user_id="1", session=None)
            return None
        except fastapi.HTTPException as exc:
            return exc
    finally:
        limits_mod.billing_service = orig


def test_require_feature_passes_get() -> None:
    exc = _dep("priming_enabled", "free", "GET")
    assert exc is None


def test_require_feature_blocks_post_on_free() -> None:
    exc = _dep("priming_enabled", "free", "POST")
    assert exc is not None
    assert exc.status_code == 402
    assert exc.detail["reason"] == "feature_locked"
    assert exc.detail["feature"] == "priming_enabled"
    assert exc.detail["plan_id"] == "free"


def test_require_feature_allows_post_on_pro() -> None:
    exc = _dep("priming_enabled", "pro", "POST")
    assert exc is None
