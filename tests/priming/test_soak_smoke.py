"""Smoke-тест soak-харнесса (prompt 7.8): прогоняет 7 дней в оффлайне
и валидирует, что распределение сходится с DRY_RUN_DISTRIBUTION и ни
один сценарий не роняет скрипт.
"""

from __future__ import annotations

from scripts.priming_soak.soak import FAIL_THRESHOLDS, _report, run_soak


def test_default_soak_passes_fail_thresholds() -> None:
    stats = run_soak(
        days=7,
        accounts=5,
        warmup_profile="warm",
        humanizer_mode="balanced",
        daily_cap=35,
        seed=42,
    )
    report, failures = _report(stats)
    assert failures == [], (report, failures)
    assert report["attempts"] > 100
    assert report["primed_ratio"] >= FAIL_THRESHOLDS["min_primed_ratio"]
    assert report["flood_ratio"] <= FAIL_THRESHOLDS["max_flood_ratio"]


def test_humanizer_off_leaves_zero_beats() -> None:
    stats = run_soak(
        days=1,
        accounts=2,
        warmup_profile="warm",
        humanizer_mode="off",
        daily_cap=35,
        seed=1,
    )
    assert stats.humanizer_beats == 0


def test_cold_profile_produces_fewer_attempts_than_hot() -> None:
    cold = run_soak(
        days=3, accounts=3, warmup_profile="cold",
        humanizer_mode="off", daily_cap=35, seed=7,
    )
    hot = run_soak(
        days=3, accounts=3, warmup_profile="hot",
        humanizer_mode="off", daily_cap=35, seed=7,
    )
    assert cold.attempts < hot.attempts
