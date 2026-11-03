"""structlog в JSON-формате для воркера."""

from __future__ import annotations

import logging
import sys

import structlog

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Настраивает structlog на JSON-вывод. Идемпотентна.

    ВАЖНО: пишем в stderr, а не в stdout (дефолт PrintLoggerFactory). stdout у
    CPython на Windows под `uvicorn --reload` идёт через pipe в процесс
    перезагрузчика и буферизуется БЛОКАМИ — JSON-лог необработанного
    исключения (api.unhandled_exception) мог застрять в буфере и не попасть
    в терминал, пока буфер не заполнится или процесс не завершится (баг-репорт
    «500 в консоли нет вообще нигде», хотя запрос реально падал). stderr в
    CPython гарантированно без такой буферизации — пишется сразу.
    """
    global _configured
    if _configured:
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(*args, **kwargs) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(*args, **kwargs)
