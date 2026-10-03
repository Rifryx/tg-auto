"""Промпт 3.2b: ORM parsing (metadata-уровень)."""

from __future__ import annotations

from core.models.base import PARSING_SCHEMA
from modules.parsing.models import ParsedList, ParsedListTarget


def test_tables_in_parsing_schema() -> None:
    assert ParsedList.__table__.schema == PARSING_SCHEMA
    assert ParsedListTarget.__table__.schema == PARSING_SCHEMA


def test_list_target_fk_and_unique() -> None:
    fks = {
        fk.parent.name: (fk.column.table.fullname, fk.ondelete or "")
        for fk in ParsedListTarget.__table__.foreign_keys
    }
    assert fks["list_id"] == (f"{PARSING_SCHEMA}.lists", "CASCADE")
    idx_names = {i.name for i in ParsedListTarget.__table__.indexes}
    assert "ix_list_targets_list_tg_user" in idx_names


def test_list_columns() -> None:
    cols = {c.name for c in ParsedList.__table__.columns}
    assert {
        "id", "owner_user_id", "name", "source_kind", "chat_ref",
        "days_window", "min_messages", "raw_count", "after_filters_count",
        "filters_breakdown", "parsed_at", "created_at",
    }.issubset(cols)
