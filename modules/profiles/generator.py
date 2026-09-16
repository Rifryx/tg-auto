"""AI-генерация оформления Telegram-профиля из персоны (этап 6 УТП).

Персона (``core.models.Persona``) — тематический портрет: `name`,
`personality_tags`, `bio_template`. LLM превращает его в компактный набор
подписей аккаунта, которые дальше применяются через ``UpdateProfileRequest`` /
``UpdateUsernameRequest``.

Дизайн:
* Провайдер LLM инъектируется (тот же ``worker.llm.LLMProvider``). Тесты
  подставляют FakeProvider — сеть не поднимается.
* Возвращает ``GeneratedProfile`` с уже нормализованными полями (лимиты
  Telegram: имя ≤64, фамилия ≤64, био ≤70, username 5–32 [a-zA-Z0-9_]).
* Формат ответа LLM — строгий JSON; при парсинг-фейле используем эвристический
  fallback (regex по строкам вида ``key: value``), чтобы не терять весь запрос
  из-за пропущенной запятой в ответе.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel

from core.models import Persona
from worker.llm.base import LLMProvider, Message


# Telegram-лимиты (публичные): проверенные текущей клиентской документацией.
NAME_MAX = 64
BIO_MAX = 70
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


SYSTEM_PROMPT = """
Ты — генератор данных для Telegram-профиля. По портрету персонажа (persona)
верни строго JSON без комментариев в формате:

{
  "first_name": "<строка, ≤64 символов>",
  "last_name": "<строка или пустая строка, ≤64>",
  "bio": "<строка ≤70 символов, звучит естественно, без хэштегов и ссылок>",
  "username_candidates": ["<5-32 символа, латиница/цифры/подчёркивание, начинается с буквы>", ...]
}

Требования:
* Возвращай именно JSON и ничего сверху/снизу.
* first_name/last_name — на языке из personality_tags, если указан (напр. "ru", "en"),
  иначе — латиницей.
* bio — от лица персонажа, живой тон; никаких «нейросеть», «AI», «GPT», «сгенерировано».
* username_candidates — от 3 до 6 вариантов; варьируй суффиксы, разделители,
  сокращения; НЕ используй имя и фамилию буквально (это утечка LLM-паттерна).
""".strip()


@dataclass
class GeneratedProfile:
    """Результат генерации, готовый к применению через Telethon."""

    first_name: str
    last_name: str = ""
    bio: str = ""
    username_candidates: list[str] = field(default_factory=list)
    raw: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "bio": self.bio,
            "username_candidates": list(self.username_candidates),
        }


class ProfileGenerationError(RuntimeError):
    """Не удалось получить осмысленный профиль (пустой ответ LLM)."""


class ProfileGenerator:
    """Генератор профилей поверх абстрактного ``LLMProvider``."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_tokens: int = 400,
        temperature: float = 0.85,
    ) -> None:
        self._provider = provider
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def generate(self, persona: Persona) -> GeneratedProfile:
        user_prompt = _persona_to_user_prompt(persona)
        raw = await self._provider.generate(
            system=SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_prompt)],
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )
        raw = (raw or "").strip()
        if not raw:
            raise ProfileGenerationError("empty LLM response")

        parsed = _parse_response(raw)
        return _normalize(parsed, raw=raw)


# ── helpers ───────────────────────────────────────────────────────────────────
def _persona_to_user_prompt(persona: Persona) -> str:
    tags = ", ".join(persona.personality_tags or []) if persona else ""
    lines = [
        f"persona.name: {persona.name}" if persona else "",
        f"persona.personality_tags: [{tags}]",
    ]
    if persona and persona.bio_template:
        lines.append(f"persona.bio_template (стилевой ориентир): {persona.bio_template}")
    return "\n".join(l for l in lines if l)


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")
_KEY_LINE = re.compile(
    r'^\s*"?(first_name|last_name|bio|username_candidates)"?\s*:\s*(.+?)\s*,?$',
    re.MULTILINE,
)


def _parse_response(raw: str) -> dict[str, object]:
    """JSON первой попыткой; при провале — эвристика по строкам ``key: value``."""
    match = _JSON_BLOCK.search(raw)
    if match is not None:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Fallback: собираем ключи руками. Никогда не молчим — вернём что есть.
    parsed: dict[str, object] = {}
    for m in _KEY_LINE.finditer(raw):
        key, value = m.group(1), m.group(2).strip()
        if key == "username_candidates":
            parsed[key] = [
                v.strip().strip('"').strip("'")
                for v in re.split(r"[,\[\]]", value)
                if v.strip()
            ]
        else:
            parsed[key] = value.strip('"').strip("'")
    return parsed


def _normalize(parsed: dict[str, object], *, raw: str) -> GeneratedProfile:
    first_name = _clip(_as_str(parsed.get("first_name")), NAME_MAX)
    if not first_name:
        # Имени нет — это провал: без first_name бесполезно применять профиль.
        raise ProfileGenerationError(f"parsed profile without first_name: {raw!r}")
    last_name = _clip(_as_str(parsed.get("last_name")), NAME_MAX)
    bio = _clip(_as_str(parsed.get("bio")), BIO_MAX)

    raw_candidates = parsed.get("username_candidates") or []
    if isinstance(raw_candidates, str):
        raw_candidates = [raw_candidates]
    seen: set[str] = set()
    candidates: list[str] = []
    for c in raw_candidates:
        u = _clean_username(_as_str(c))
        if u and u.lower() not in seen and USERNAME_RE.match(u):
            seen.add(u.lower())
            candidates.append(u)

    return GeneratedProfile(
        first_name=first_name,
        last_name=last_name,
        bio=bio,
        username_candidates=candidates,
        raw=raw,
    )


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clip(value: str, limit: int) -> str:
    return value[:limit] if len(value) > limit else value


def _clean_username(value: str) -> str:
    # У Telegram username: 5–32 символа, начинается с буквы; допустимы только
    # латиница/цифры/подчёркивание. Убираем @, префиксы t.me, обрезаем длину.
    v = value.strip().lstrip("@")
    v = re.sub(r"^https?://t\.me/", "", v, flags=re.IGNORECASE)
    v = re.sub(r"[^A-Za-z0-9_]", "", v)
    return v[:32]


# Единая точка получения генератора по имени провайдера. Импорт лениво, чтобы
# ``modules.profiles`` не тянул сеть при простом импорте пакета.
def default_generator(provider_name: str = "deepseek") -> ProfileGenerator:
    from worker.llm.factory import get_provider

    return ProfileGenerator(get_provider(provider_name))
