"""Лёгкий разбор markdown-разметки первого поста в Telegram-entities.

Встроенные парсеры Telethon 1.44 (md/html) не умеют спойлер, поэтому для
«текста с эффектами» (жирный/курсив/зачёркнутый/скрытый/моноширинный/ссылка)
мы собираем ``MessageEntity*`` вручную и передаём их в ``send_message`` /
``send_file`` через ``formatting_entities``. Так разметка не зависит от
капризов parse_mode и экранирования.

Поддерживаемые маркеры (не вложенные — ровно то, что ставит тулбар на фронте,
оборачивая выделение):

* ``**жирный**``        → bold
* ``__курсив__``        → italic
* ``~~зачёркнутый~~``   → strike
* ``||скрытый||``       → spoiler
* `` `моно` ``          → code
* ``[текст](url)``      → ссылка

Смещения/длины — в единицах UTF-16 (как считает Telegram), иначе эмодзи и
не-BMP символы сдвигают разметку.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityCode,
    MessageEntityItalic,
    MessageEntitySpoiler,
    MessageEntityStrike,
    MessageEntityTextUrl,
    TypeMessageEntity,
)

# (открывающий, закрывающий, класс entity). Первые символы различны —
# префиксных коллизий нет.
_PAIRS = [
    ("||", "||", MessageEntitySpoiler),
    ("**", "**", MessageEntityBold),
    ("~~", "~~", MessageEntityStrike),
    ("__", "__", MessageEntityItalic),
    ("`", "`", MessageEntityCode),
]

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _u16(text: str) -> int:
    """Длина строки в единицах UTF-16 (как считает Telegram)."""
    return len(text.encode("utf-16-le")) // 2


def markdown_to_entities(src: str) -> Tuple[str, List[TypeMessageEntity]]:
    """Разобрать markdown-подобную строку в (plain_text, entities).

    Разметка плоская: маркеры внутри уже открытого спана трактуются как текст.
    Непарные/пустые маркеры остаются обычным текстом.
    """
    out: List[str] = []
    entities: List[TypeMessageEntity] = []
    pos = 0  # смещение в UTF-16 для уже собранного out
    i = 0
    n = len(src)

    while i < n:
        ch = src[i]

        # Ссылка [текст](url)
        if ch == "[":
            m = _LINK_RE.match(src, i)
            if m:
                label, url = m.group(1), m.group(2)
                ln = _u16(label)
                entities.append(
                    MessageEntityTextUrl(offset=pos, length=ln, url=url)
                )
                out.append(label)
                pos += ln
                i = m.end()
                continue

        # Парные маркеры
        matched = False
        for open_m, close_m, ent_cls in _PAIRS:
            if src.startswith(open_m, i):
                start = i + len(open_m)
                close = src.find(close_m, start)
                if close > start:  # непустое содержимое
                    inner = src[start:close]
                    ln = _u16(inner)
                    entities.append(ent_cls(offset=pos, length=ln))
                    out.append(inner)
                    pos += ln
                    i = close + len(close_m)
                    matched = True
                    break
        if matched:
            continue

        # Обычный символ
        out.append(ch)
        pos += _u16(ch)
        i += 1

    return "".join(out), entities
