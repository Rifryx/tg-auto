"""configure_logging настраивает structlog на вывод в stderr, а не в stdout.

Баг-репорт: под `uvicorn --reload` на Windows stdout процесса идёт через pipe
в перезагрузчик и буферизуется БЛОКАМИ — JSON-лог необработанного исключения
(api.unhandled_exception) застревал в буфере и не появлялся в терминале, пока
буфер не заполнится или процесс не завершится. stderr у CPython пишется сразу
(без такой буферизации) — в этом и фикс.

Тест НЕ трогает реальное глобальное состояние structlog (structlog.configure
мутирует процесс-глобальный конфиг и кэширует логгеры — порча его тут ломала
бы логирование во всех остальных тестах сессии). Вместо этого перехватываем
сам вызов structlog.configure() и проверяем, каким фабрике/потоку он был бы
передан.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import structlog


def test_configure_logging_uses_stderr_print_logger_factory():
    import worker.tasks.logging as logging_mod

    logging_mod._configured = False  # обходим идемпотентность для теста
    try:
        with patch("structlog.configure") as mock_configure:
            logging_mod.configure_logging()
    finally:
        logging_mod._configured = False  # не оставляем «сконфигурировано» для реального импорта

    assert mock_configure.called
    factory = mock_configure.call_args.kwargs["logger_factory"]
    assert isinstance(factory, structlog.PrintLoggerFactory)
    # PrintLoggerFactory хранит переданный file как приватный атрибут _file.
    assert getattr(factory, "_file", None) is sys.stderr
