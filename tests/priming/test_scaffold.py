"""Промпт 1.1: каркас модуля прайминга и схема БД.

Проверяем, что все подпакеты импортируются и что константа схемы объявлена.
Модели/репозитории/эндпоинты появятся на следующих промптах.
"""

from __future__ import annotations

import importlib

import pytest


PRIMING_SUBPACKAGES = [
    "modules.priming",
    "modules.priming.api",
    "modules.priming.models",
    "modules.priming.repositories",
    "modules.priming.schemas",
    "modules.priming.worker",
    "modules.priming.parser",
    "modules.priming.profile_setup",
]


@pytest.mark.parametrize("dotted", PRIMING_SUBPACKAGES)
def test_subpackage_imports(dotted: str) -> None:
    importlib.import_module(dotted)


def test_priming_schema_constant() -> None:
    from core.models.base import PRIMING_SCHEMA

    assert PRIMING_SCHEMA == "priming"


def test_priming_schema_migration_exists() -> None:
    """0039 должна создавать схему priming и не иметь моделей поверх неё."""
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0039_priming_schema.py"
    )
    assert migration.exists(), "migration 0039_priming_schema.py must exist"

    text = migration.read_text()
    assert 'PRIMING = "priming"' in text
    assert 'CREATE SCHEMA IF NOT EXISTS' in text
    assert 'DROP SCHEMA IF EXISTS' in text
    assert 'revision: str = "0039"' in text
    assert 'down_revision: Union[str, None] = "0038"' in text
