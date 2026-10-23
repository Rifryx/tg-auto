"""Воркер не должен импортировать пакет ``api``.

``Dockerfile.worker`` копирует в образ только ``core``, ``worker``, ``modules``
(без ``api``/``bot``) — любой импорт из ``api`` где-то в цепочке, достижимой
из ``worker.main``, валит контейнер при старте с ``ModuleNotFoundError: No
module named 'api'`` (реальный инцидент: ``worker/tasks/accounts.py`` когда-то
импортировал ``api.services.accounts.delete_account`` напрямую — воркер падал
в цикле рестартов, фоновые задачи никогда не выполнялись).

Статическая проверка (AST, без выполнения кода) по всем ``.py`` в ``worker/``
и ``core/`` — модулям, которые реально копируются в образ воркера.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGES = ("worker", "core")


def _api_imports(path: Path) -> list[str]:
    """Список модулей вида ``api...``, импортируемых данным файлом (top-level)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # level > 0 — относительный импорт (`from . import x`), не наш случай.
            if node.level == 0 and node.module and (
                node.module == "api" or node.module.startswith("api.")
            ):
                found.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "api" or alias.name.startswith("api."):
                    found.append(alias.name)
    return found


def test_worker_and_core_never_import_api_package():
    offenders: dict[str, list[str]] = {}
    for pkg in WORKER_PACKAGES:
        for path in (REPO_ROOT / pkg).rglob("*.py"):
            imports = _api_imports(path)
            if imports:
                offenders[str(path.relative_to(REPO_ROOT))] = imports

    assert not offenders, (
        "worker/core импортируют пакет 'api', которого нет в образе воркера "
        f"(Dockerfile.worker не копирует api/) — воркер упадёт при старте: {offenders}"
    )
