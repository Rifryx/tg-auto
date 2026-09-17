"""Gunicorn-конфиг для прод-запуска API (PROJECT-STAGES §6; аудит #5).

Запуск::

    gunicorn -c deploy/gunicorn.conf.py api.asgi:app

Все параметры сети/таймаутов берутся из ENV (с разумными дефолтами), число
воркеров ограничено сверху (small-scale деплой одной машиной, см. §6).
"""

from __future__ import annotations

import multiprocessing
import os

# --- сеть ---
bind = os.getenv("API_BIND", "0.0.0.0:8000")

# --- воркеры ---
# 2*CPU+1 — обычная эвристика, но ограничиваем потолком (одна небольшая машина).
_MAX_WORKERS = int(os.getenv("API_MAX_WORKERS", "4"))
workers = min(2 * multiprocessing.cpu_count() + 1, _MAX_WORKERS)
worker_class = "uvicorn.workers.UvicornWorker"

# --- таймауты ---
timeout = int(os.getenv("API_TIMEOUT", "30"))
graceful_timeout = int(os.getenv("API_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("API_KEEPALIVE", "5"))

# --- логи (в stdout/stderr; агрегатор снаружи) ---
accesslog = os.getenv("API_ACCESS_LOG", "-")
errorlog = os.getenv("API_ERROR_LOG", "-")
loglevel = os.getenv("API_LOG_LEVEL", "info")
