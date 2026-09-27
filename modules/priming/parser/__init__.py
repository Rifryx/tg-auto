"""Парсер вынесен в отдельный модуль-сервис ``modules.parsing``.

Импортируйте оттуда:
    from modules.parsing.parser.chat_messages import parse_chat_messages
    from modules.parsing.parser.chat_members import parse_chat_members
    from modules.parsing.parser.filters import FilterOptions, apply_filters

Прайминг больше не хранит парсер-результаты в своей схеме; он
импортирует готовые списки через
``POST /modules/priming/campaigns/{id}/targets/import-list``.
"""
