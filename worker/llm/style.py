"""StyleRandomizer — «очеловечивание» сгенерированного текста (PROJECT-STAGES §7).

Чистые функции, без сети/БД. Каждое правило срабатывает с заданной вероятностью;
все вероятности — константы (легко подкрутить) и переопределяемы в конструкторе.
Персона (``personality_tags``) корректирует вероятности простым маппингом.

RNG инъектируется (``random.Random``) — с одним seed результат детерминирован.
"""

from __future__ import annotations

import random
import re
from typing import Optional

# --- вероятности по умолчанию (§7) ------------------------------------------
P_SHORTEN = 0.15   # обрезать до первого предложения
P_EMOJI = 0.25     # убрать/добавить emoji (макс 1)
P_TYPO = 0.10      # опечатка (соседняя клавиша QWERTY)
P_CASE = 0.20      # регистр начала / точка в конце

_EMOJIS = ("🙂", "👍", "🔥", "😂", "💯", "🤔", "✨", "😅")

# Диапазоны для детекции emoji в тексте.
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2190, 0x21FF),
    (0xFE00, 0xFE0F),
)

# Соседи по QWERTY (по строкам, горизонтальные соседи).
_QWERTY_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_NEIGHBORS: dict[str, list[str]] = {}
for _row in _QWERTY_ROWS:
    for _i, _ch in enumerate(_row):
        _adj = []
        if _i > 0:
            _adj.append(_row[_i - 1])
        if _i < len(_row) - 1:
            _adj.append(_row[_i + 1])
        _NEIGHBORS[_ch] = _adj

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]+")


def _is_emoji(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _EMOJI_RANGES)


class StyleRandomizer:
    def __init__(
        self,
        rng: Optional[random.Random] = None,
        *,
        p_shorten: float = P_SHORTEN,
        p_emoji: float = P_EMOJI,
        p_typo: float = P_TYPO,
        p_case: float = P_CASE,
    ) -> None:
        self._rng = rng or random.Random()
        self.p_shorten = p_shorten
        self.p_emoji = p_emoji
        self.p_typo = p_typo
        self.p_case = p_case

    # -- публичный API --------------------------------------------------------

    def randomize(self, text: str, persona=None) -> str:
        p_shorten, p_emoji, p_typo, p_case = self._probabilities(persona)
        result = text
        if self._rng.random() < p_shorten:
            result = self._shorten(result)
        if self._rng.random() < p_emoji:
            result = self._toggle_emoji(result)
        if self._rng.random() < p_typo:
            result = self._typo(result)
        if self._rng.random() < p_case:
            result = self._tweak_case(result)
        return result

    # -- влияние персоны ------------------------------------------------------

    def _probabilities(self, persona) -> tuple[float, float, float, float]:
        p_shorten, p_emoji, p_typo, p_case = (
            self.p_shorten,
            self.p_emoji,
            self.p_typo,
            self.p_case,
        )
        tags = set(getattr(persona, "personality_tags", None) or [])
        if "formal" in tags:
            p_typo = 0.0
            p_emoji *= 0.3
        if "casual" in tags:
            p_typo = min(1.0, p_typo * 1.5)
            p_emoji = min(1.0, p_emoji * 1.5)
        # 'sarcastic' — оставляем вероятности как есть.
        return p_shorten, p_emoji, p_typo, p_case

    # -- правила --------------------------------------------------------------

    @staticmethod
    def _shorten(text: str) -> str:
        parts = _SENTENCE_SPLIT.split(text.strip())
        return parts[0] if parts else text

    def _toggle_emoji(self, text: str) -> str:
        if any(_is_emoji(ch) for ch in text):
            return "".join(ch for ch in text if not _is_emoji(ch)).rstrip()
        return f"{text.rstrip()} {self._rng.choice(_EMOJIS)}"

    def _typo(self, text: str) -> str:
        # Кандидаты: слова, где есть внутренний символ (не первый/не последний).
        words = [
            m for m in _WORD.finditer(text)
            if m.end() - m.start() >= 3
        ]
        self._rng.shuffle(words)
        for match in words:
            start, end = match.start(), match.end()
            inner = list(range(start + 1, end - 1))
            self._rng.shuffle(inner)
            for pos in inner:
                ch = text[pos]
                neighbors = _NEIGHBORS.get(ch.lower())
                if not neighbors:
                    continue
                repl = self._rng.choice(neighbors)
                if ch.isupper():
                    repl = repl.upper()
                return text[:pos] + repl + text[pos + 1:]
        return text

    def _tweak_case(self, text: str) -> str:
        if not text:
            return text
        choice = self._rng.random()
        if choice < 0.5:
            # регистр первого буквенного символа
            for i, ch in enumerate(text):
                if ch.isalpha():
                    flipped = ch.lower() if ch.isupper() else ch.upper()
                    return text[:i] + flipped + text[i + 1:]
            return text
        # убрать точку в конце
        stripped = text.rstrip()
        if stripped.endswith("."):
            return stripped[:-1]
        return text
