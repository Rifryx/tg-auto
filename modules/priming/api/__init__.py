"""API-слой модуля прайминга.

Роутер живёт в ``modules.priming.api.router``. Импортируйте его напрямую
(``from modules.priming.api.router import router``) — не через реэкспорт
из этого пакета, чтобы не тянуть FastAPI/Redis/task-queue при простом
``import modules.priming`` (это ломает лёгкие unit-тесты и провоцирует
цикл через ``core.models.__init__``).
"""
