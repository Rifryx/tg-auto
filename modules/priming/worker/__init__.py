"""Worker-задачи модуля прайминга.

- ``trigger.py`` — TriggerRunner (промпт 2.1).
- ``executor.py`` — единица прайминга (промпт 2.2).
- ``orchestrator.py`` — раскладчик по кампаниям (промпт 2.3).
- ``humanizer.py`` — фоновая имитация (промпт 5.1).

Модули НЕ реэкспортируются на уровне ``__init__``, потому что
``trigger.py`` тянет Telethon и не должен грузиться при простом
``import modules.priming`` (это ломает лёгкие unit-тесты).
Используйте прямые импорты, например
``from modules.priming.worker.trigger import TriggerRunner``.
"""
