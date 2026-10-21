"""Реэкспорт ORM модуля ``parsing``.

Канонические определения — в ``modules/parsing/models``. Реэкспорт нужен,
чтобы Alembic и общий ``core.models`` видели таблицы.
"""

from modules.parsing.models import ParsedList, ParsedListTarget, ParsingJob

__all__ = ["ParsedList", "ParsedListTarget", "ParsingJob"]
