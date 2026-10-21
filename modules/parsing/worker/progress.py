"""Живой прогресс и управление парсингом (пауза/стоп) для воркера.

``ParsingProgress`` оборачивает ``ParsingJobRepository`` и даёт парсерам
удобные точки:

* ``log(msg)``       — добавить строку в ленту задачи (видна в UI в реальном
  времени через поллинг);
* ``set_counts(...)``— обновить счётчики собранных/вставленных;
* ``await heartbeat(raw=...)`` — обновить прогресс и среагировать на управление:
  при ``pause`` крутится, пока пользователь не снимет паузу или не остановит;
  при ``stop`` бросает :class:`ParsingStopped` (ловит dispatch → status=stopped).

Каждая запись идёт в своей короткой сессии (``session_factory``) и коммитится —
чтобы UI видел изменения немедленно, не дожидаясь конца задачи.

``NullProgress`` — заглушка для прямых вызовов парсеров (тесты/старые пути) без
задачи: все методы — no-op.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from modules.parsing.repositories.job import ParsingJobRepository


class ParsingStopped(Exception):
    """Пользователь остановил парсинг — прерываем сбор, финализируем частично."""


class NullProgress:
    """Заглушка: прогресс/управление отсутствуют."""

    def log(self, _msg: str) -> None:  # noqa: D401
        return None

    def set_counts(self, *, raw: Optional[int] = None, inserted: Optional[int] = None) -> None:
        return None

    async def heartbeat(self, *, raw: Optional[int] = None) -> None:
        return None


class ParsingProgress:
    def __init__(
        self,
        session_factory: Callable[[], Any],
        job_id: int,
        *,
        pause_poll_seconds: float = 1.0,
    ) -> None:
        self._sf = session_factory
        self._job_id = job_id
        self._pause_poll = pause_poll_seconds

    def _with_repo(self, fn):
        with self._sf() as session:
            result = fn(ParsingJobRepository(session))
            session.commit()
            return result

    def log(self, msg: str) -> None:
        self._with_repo(lambda repo: repo.append_log(self._job_id, msg))

    def set_counts(
        self, *, raw: Optional[int] = None, inserted: Optional[int] = None
    ) -> None:
        self._with_repo(
            lambda repo: repo.set_counts(self._job_id, raw=raw, inserted=inserted)
        )

    def read_control(self) -> str:
        return self._with_repo(lambda repo: repo.read_control(self._job_id))

    async def heartbeat(self, *, raw: Optional[int] = None) -> None:
        """Обновляет прогресс и реагирует на pause/stop."""
        if raw is not None:
            self.set_counts(raw=raw)
        control = self.read_control()
        if control == "stop":
            raise ParsingStopped()
        # Пауза: крутимся, пока не снимут или не остановят.
        while control == "pause":
            await asyncio.sleep(self._pause_poll)
            control = self.read_control()
            if control == "stop":
                raise ParsingStopped()
