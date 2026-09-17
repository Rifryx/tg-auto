"""Проверки прод-обвязки деплоя (аудит #10): entrypoint мигрирует до старта."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ENTRYPOINT = _ROOT / "deploy" / "entrypoint-api.sh"


def test_entrypoint_runs_alembic_before_gunicorn():
    assert _ENTRYPOINT.exists(), "нет deploy/entrypoint-api.sh"
    text = _ENTRYPOINT.read_text(encoding="utf-8")

    assert "alembic upgrade head" in text
    assert "gunicorn" in text and "api.asgi:app" in text
    # порядок: миграции строго ДО запуска сервера
    assert text.index("alembic upgrade head") < text.index("gunicorn")
    # сервер запускается через exec (замена процесса, корректные сигналы)
    assert "exec gunicorn" in text
    # использует наш конфиг gunicorn
    assert "deploy/gunicorn.conf.py" in text


def test_entrypoint_fails_fast():
    # set -e: любая ошибка (в т.ч. упавший alembic) прерывает запуск
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    assert "set -e" in text or "set -eu" in text
