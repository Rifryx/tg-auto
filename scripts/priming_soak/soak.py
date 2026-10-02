"""Soak-тест модуля прайминга (prompt 7.8).

Offline-симуляция 7 дней работы кампании без Telethon / Redis / arq:

* Шаг = один «час» симулированного времени;
* Каждый час каждому не-quarantined аккаунту даётся до
  effective_daily_limit(warmup_profile, warmup_started_at) / 24 попыток
  (с округлением), outcome розыгрывается по DRY_RUN_DISTRIBUTION;
* FLOOD_WAIT'ы увеличивают consecutive-счётчик; на 3-й подряд аккаунт
  уходит в quarantined и выпадает из пула;
* Параллельно считаем humanizer-ticks (один beat на пару (аккаунт, час)
  при не-OFF humanizer-режиме).

После всех итераций печатаем агрегат и, если какие-то допуски нарушены,
падаем с non-zero exit code — пригодно для CI-nightly.

Запуск: `python scripts/priming_soak/soak.py --days 7 --accounts 5`.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Делаем модули проекта импортируемыми при запуске из корня.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.config.priming_warmup import effective_daily_limit  # noqa: E402


# ── Распределение outcome'ов (копия DRY_RUN_DISTRIBUTION, чтобы не
#    тащить telethon-зависимый импорт из modules.priming.worker.trigger).
DRY_RUN_DIST = (
    ("primed", 0.78),
    ("privacy_restricted", 0.12),
    ("flood_wait", 0.08),
    ("deleted", 0.02),
)

MAX_FLOOD_WAITS = 3

# Пороги фейла — любое превышение/недобор валит процесс.
FAIL_THRESHOLDS = {
    "min_primed_ratio": 0.30,
    "max_flood_ratio": 0.20,
    "min_humanizer_beats": 1,
}


def _draw(rng: random.Random) -> str:
    dice = rng.random()
    cum = 0.0
    for outcome, weight in DRY_RUN_DIST:
        cum += weight
        if dice < cum:
            return outcome
    return DRY_RUN_DIST[0][0]


@dataclass
class _Account:
    id: int
    warmup_started_at: datetime
    primes_today: int = 0
    primes_total: int = 0
    flood_consecutive: int = 0
    quarantined: bool = False


@dataclass
class _Stats:
    attempts: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    quarantined: int = 0
    humanizer_beats: int = 0

    def record(self, outcome: str) -> None:
        self.attempts += 1
        self.outcomes[outcome] = self.outcomes.get(outcome, 0) + 1


def run_soak(
    *,
    days: int,
    accounts: int,
    warmup_profile: str,
    humanizer_mode: str,
    daily_cap: int,
    seed: int,
) -> _Stats:
    rng = random.Random(seed)
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    pool = [
        _Account(id=i, warmup_started_at=now) for i in range(1, accounts + 1)
    ]
    stats = _Stats()

    hours_total = days * 24
    for hour in range(hours_total):
        clock = now + timedelta(hours=hour)
        # В начале новых суток обнуляем primes_today.
        if hour > 0 and clock.hour == 0:
            for a in pool:
                a.primes_today = 0

        for a in pool:
            if a.quarantined:
                continue
            # Эффективный лимит с учётом рампы.
            eff = effective_daily_limit(
                warmup_profile,
                a.warmup_started_at,
                clock,
                campaign_cap=daily_cap,
            )
            remaining_today = max(0, eff - a.primes_today)
            # Равномерно размазываем по 24ч, но минимум 1 если ещё остался
            # запас — иначе маленькие лимиты никогда не отработают.
            per_hour = max(1, remaining_today // 24) if remaining_today > 0 else 0
            per_hour = min(per_hour, remaining_today)

            for _ in range(per_hour):
                outcome = _draw(rng)
                stats.record(outcome)
                if outcome == "flood_wait":
                    a.flood_consecutive += 1
                    if a.flood_consecutive >= MAX_FLOOD_WAITS:
                        a.quarantined = True
                        stats.quarantined += 1
                        break
                else:
                    a.flood_consecutive = 0
                    a.primes_today += 1
                    a.primes_total += 1

            # Humanizer beat — один per hour per аккаунт, если включён.
            if not a.quarantined and humanizer_mode != "off":
                stats.humanizer_beats += 1

    return stats


def _report(stats: _Stats) -> tuple[dict, list[str]]:
    """Собирает плоский отчёт и список нарушенных допусков."""
    attempts = max(1, stats.attempts)
    primed_ratio = stats.outcomes.get("primed", 0) / attempts
    flood_ratio = stats.outcomes.get("flood_wait", 0) / attempts
    privacy_ratio = stats.outcomes.get("privacy_restricted", 0) / attempts
    report = {
        "attempts": stats.attempts,
        "outcomes": stats.outcomes,
        "primed_ratio": round(primed_ratio, 4),
        "flood_ratio": round(flood_ratio, 4),
        "privacy_ratio": round(privacy_ratio, 4),
        "quarantined_accounts": stats.quarantined,
        "humanizer_beats": stats.humanizer_beats,
    }
    failures: list[str] = []
    if primed_ratio < FAIL_THRESHOLDS["min_primed_ratio"]:
        failures.append(
            f"primed_ratio={primed_ratio:.3f} < "
            f"{FAIL_THRESHOLDS['min_primed_ratio']}"
        )
    if flood_ratio > FAIL_THRESHOLDS["max_flood_ratio"]:
        failures.append(
            f"flood_ratio={flood_ratio:.3f} > "
            f"{FAIL_THRESHOLDS['max_flood_ratio']}"
        )
    if stats.humanizer_beats < FAIL_THRESHOLDS["min_humanizer_beats"]:
        failures.append(
            f"humanizer_beats={stats.humanizer_beats} < "
            f"{FAIL_THRESHOLDS['min_humanizer_beats']}"
        )
    return report, failures


def main() -> int:
    ap = argparse.ArgumentParser(description="Priming soak harness")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--accounts", type=int, default=5)
    ap.add_argument(
        "--warmup-profile",
        default="warm",
        choices=["cold", "warm", "hot"],
    )
    ap.add_argument(
        "--humanizer-mode",
        default="balanced",
        choices=["off", "balanced", "aggressive"],
    )
    ap.add_argument("--daily-cap", type=int, default=35)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", action="store_true", help="JSON output for CI")
    args = ap.parse_args()

    stats = run_soak(
        days=args.days,
        accounts=args.accounts,
        warmup_profile=args.warmup_profile,
        humanizer_mode=args.humanizer_mode,
        daily_cap=args.daily_cap,
        seed=args.seed,
    )
    report, failures = _report(stats)

    if args.json:
        print(json.dumps({"report": report, "failures": failures}, indent=2))
    else:
        print(
            f"soak {args.days}d × {args.accounts} acc "
            f"profile={args.warmup_profile} humanizer={args.humanizer_mode}"
        )
        print(f"  attempts: {report['attempts']}")
        print(f"  primed:   {report['primed_ratio']:.1%}")
        print(f"  flood:    {report['flood_ratio']:.1%}")
        print(f"  privacy:  {report['privacy_ratio']:.1%}")
        print(f"  quarantined accounts: {report['quarantined_accounts']}")
        print(f"  humanizer beats:      {report['humanizer_beats']}")
        if failures:
            print("FAIL:")
            for f in failures:
                print(f"  - {f}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
