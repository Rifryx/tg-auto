"""Оффлайн smoke: репозитории импортятся и несут обязательные методы.

Настоящие DB-тесты (с postgres_test) — в test_repositories_db.py; они
падают без Postgres, но smoke-тест ловит поломки интерфейсов раньше.
"""

from __future__ import annotations

import pytest

from modules.priming.repositories import (
    AnchorChannelRepository,
    BlacklistRepository,
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    FloodIncidentRepository,
    TargetSourceRepository,
)


REPO_REQUIRED_COMMON = ["get", "get_by_id"]  # get унаследован от BaseRepository


@pytest.mark.parametrize(
    "repo_cls, extras",
    [
        (CampaignRepository, ["list_all", "list_by_status", "create", "update",
                              "set_status", "delete_hard"]),
        (CampaignAccountRepository, ["list_by_campaign", "create", "update",
                                     "delete_hard", "acquire_next",
                                     "release_after_prime", "quarantine",
                                     "reset_daily_counters"]),
        (CampaignTargetRepository, ["list_by_campaign", "count_by_status",
                                    "create", "bulk_create", "update",
                                    "delete_hard", "transition_status",
                                    "claim_next", "mark_result"]),
        (TargetSourceRepository, ["list_by_campaign", "create", "update",
                                  "delete_hard"]),
        (AnchorChannelRepository, ["list_by_campaign", "get_by_account",
                                   "create", "update", "delete_hard"]),
        (ExecutionLogRepository, ["list_by_campaign", "append",
                                  "recent_outcomes"]),
        (FloodIncidentRepository, ["list_by_campaign_account", "append",
                                   "delete_hard"]),
        (BlacklistRepository, ["list_by_owner", "create", "bulk_add",
                               "delete_hard", "match"]),
    ],
)
def test_repository_has_required_methods(repo_cls, extras) -> None:
    for name in REPO_REQUIRED_COMMON + extras:
        assert hasattr(repo_cls, name), (
            f"{repo_cls.__name__} missing method {name!r}"
        )
