"""Дубликат кампании (prompt 7.6).

Локальный юнит-тест на список копируемых полей — DB-путь (аккаунты/цели)
проверяется на CI под postgres_test.
"""

from __future__ import annotations

import pytest

pytest.importorskip("arq")  # service.py тянет TaskQueue

from modules.priming.api.service import _DUPLICATE_FIELDS


def test_duplicate_fields_include_config_but_not_runtime() -> None:
    # Точно копируем — конфиг:
    for f in (
        "name",
        "trigger_action",
        "trigger_actions",
        "trigger_rotation_strategy",
        "humanizer_mode",
        "warmup_profile",
        "daily_limit_per_account",
        "quiet_hours_target",
        "quiet_hours_tz",
        "ab_split_enabled",
        "ab_split_ratio",
        "dry_run",
    ):
        assert f in _DUPLICATE_FIELDS, f

    # НЕ копируем runtime — историю и статусы:
    for f in ("status", "started_at", "finished_at", "id", "created_at",
              "updated_at"):
        assert f not in _DUPLICATE_FIELDS, f
