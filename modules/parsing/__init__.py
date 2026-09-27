"""Модуль-сервис ``parsing`` — самостоятельный парсер аудитории.

Живёт рядом с commenting/shilling/priming. Прайминг импортирует готовые
списки через POST /modules/priming/campaigns/{id}/targets/import-list.

Спека и план: docs/priming-spec.md §8 (парсер), docs/priming-ui.md §5.3.
"""
