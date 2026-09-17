"""Реестр bulk-действий (этап 5 УТП).

Каждое действие — это ``BulkAction``:
* ``name``: значение из ``BulkActionType`` (единственный допустимый набор);
* ``requires_client``: нужен ли ``TelegramClient`` (пул) для выполнения;
* ``validate_payload``: pydantic-модель общего payload'а (проверяется в API);
* ``run``: асинхронная функция, выполняющая действие над одним аккаунтом.

Регистрация — через декоратор :func:`register`. Реестр — единственный источник
правды: неизвестное имя действия в API/worker блокируется.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel


class BulkActionResult(BaseModel):
    """Результат одной операции над одним аккаунтом (успех/скип с деталями)."""

    ok: bool = True
    skipped: bool = False
    detail: dict[str, Any] = {}


BulkActionRunner = Callable[..., Awaitable[BulkActionResult]]


@dataclass
class BulkAction:
    name: str
    requires_client: bool
    payload_schema: type[BaseModel]
    run: BulkActionRunner
    title: str = ""
    description: str = ""


ACTION_REGISTRY: dict[str, BulkAction] = {}


def register(action: BulkAction) -> BulkAction:
    if action.name in ACTION_REGISTRY:
        raise RuntimeError(f"bulk action already registered: {action.name}")
    ACTION_REGISTRY[action.name] = action
    return action


def get_action(name: str) -> Optional[BulkAction]:
    return ACTION_REGISTRY.get(name)
