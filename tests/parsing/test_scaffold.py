"""Промпт 3.2b: каркас модуля parsing."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("dotted", [
    "modules.parsing",
    "modules.parsing.api",
    "modules.parsing.models",
    "modules.parsing.repositories",
    "modules.parsing.schemas",
    "modules.parsing.parser",
])
def test_subpackage_imports(dotted: str) -> None:
    importlib.import_module(dotted)


def test_parsing_schema_constant() -> None:
    from core.models.base import PARSING_SCHEMA
    assert PARSING_SCHEMA == "parsing"


def test_reexport_in_core_models() -> None:
    from core import models
    from modules.parsing.models import ParsedList, ParsedListTarget
    assert models.ParsedList is ParsedList
    assert models.ParsedListTarget is ParsedListTarget
