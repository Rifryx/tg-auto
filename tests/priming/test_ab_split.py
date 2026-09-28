"""A/B split (prompt 7.3): распределение на 1000 аккаунтах ≈ ratio."""

from __future__ import annotations

import pytest

from modules.priming.worker.ab_split import (
    BUCKET_A,
    BUCKET_B,
    assign_ab_bucket,
)


def _counts(campaign_id: int, n: int, *, ratio: float) -> dict[str, int]:
    counts = {BUCKET_A: 0, BUCKET_B: 0}
    for account_id in range(1, n + 1):
        counts[assign_ab_bucket(campaign_id, account_id, ratio=ratio)] += 1
    return counts


def test_default_ratio_is_approximately_50_50_on_1000_accounts() -> None:
    counts = _counts(campaign_id=42, n=1000, ratio=0.5)
    total = sum(counts.values())
    assert total == 1000
    for bucket in (BUCKET_A, BUCKET_B):
        # ±10% допустимо на 1000 (реально стандартное отклонение ~1.6%).
        assert abs(counts[bucket] - 500) < 100, counts


def test_ratio_70_30_holds_within_tolerance() -> None:
    counts = _counts(campaign_id=7, n=1000, ratio=0.7)
    assert abs(counts[BUCKET_A] - 700) < 100, counts


def test_assignment_is_deterministic() -> None:
    for account_id in (1, 100, 999_999_999):
        first = assign_ab_bucket(1, account_id)
        second = assign_ab_bucket(1, account_id)
        assert first == second


def test_different_campaign_ids_give_independent_splits() -> None:
    # Один и тот же аккаунт в разных кампаниях может попасть
    # в разные bucket'ы (не должен «липнуть» к одной букве).
    diff = 0
    for account_id in range(1, 200):
        if assign_ab_bucket(1, account_id) != assign_ab_bucket(2, account_id):
            diff += 1
    # Ожидаем ≈50% различий; проверяем «сильно > 0».
    assert diff > 40, diff


def test_ratio_out_of_bounds_raises() -> None:
    for bad in (0.0, 1.0, -0.1, 1.1):
        with pytest.raises(ValueError):
            assign_ab_bucket(1, 1, ratio=bad)


def test_returned_values_are_only_a_or_b() -> None:
    for account_id in range(1, 200):
        assert assign_ab_bucket(1, account_id) in (BUCKET_A, BUCKET_B)
