"""Аудит админ-действий.

Компактный логгер: пишет в стандартный logging (собирается вашей инфрой),
формат — плоский JSON, чтобы легко фильтровать по actor/action. Отдельная
таблица не заводится: для нее требуется свой репозиторий, ретеншн и UI —
пока хватает лога.
"""
from __future__ import annotations

import json
import logging
from typing import Any

_logger = logging.getLogger("audit.admin")


def admin_action(actor_id: str, action: str, **payload: Any) -> None:
    """Логирует одну строку админ-аудита."""
    try:
        body = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        body = "{}"
    _logger.info("actor=%s action=%s payload=%s", actor_id, action, body)
