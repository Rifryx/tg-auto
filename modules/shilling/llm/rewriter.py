"""Рерайтер реплик шиллинга (docs/neuroshilling-spec.md § 6.1).

Когда у кампании включён ``unique_messages``, воркер прогоняет базовый текст
реплики через ``ReplicaRewriter``: LLM переписывает её «под живого человека»,
сохраняя смысл и обязательное упоминание бренда, но без ссылок и @-упоминаний.

Провайдер (``worker.llm.LLMProvider``) инъектируется — тесты подставляют
FakeProvider, сеть не поднимается.
"""

from __future__ import annotations

from typing import Optional

from worker.llm.base import LLMProvider, Message

SYSTEM_PROMPT = """
Ты — рерайтер реплик для Telegram-чата. Перепиши текст так, чтобы он звучал
естественно, как будто написан реальным пользователем.

Правила:
- Сохрани упоминание бренда/продукта ТОЧНО как задано.
- НЕ добавляй ссылки (http, t.me), @-юзернеймы, хэштеги.
- Стиль: разговорный, неформальный; лёгкие опечатки/сленг уместны.
- Длина: примерно как у оригинала (±20%).
- Верни ТОЛЬКО переписанный текст, без кавычек и пояснений.
""".strip()

# Во сколько раз максимум переписанный текст может быть длиннее оригинала.
_MAX_LEN_FACTOR = 1.5
# Нижний порог длины оригинала, ниже которого множитель 1.5 бессмысленно мал
# (для очень коротких реплик даём запас в абсолютных символах).
_MIN_LEN_BUDGET = 40


class ReplicaRewriter:
    """Переписывает одну реплику под контекст, сохраняя бренд."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_tokens: int = 200,
        temperature: float = 0.9,
    ) -> None:
        self._provider = provider
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def rewrite(
        self,
        original_text: str,
        *,
        role_name: str,
        role_character: Optional[str] = None,
        brand_name: Optional[str] = None,
        post_context: Optional[str] = None,
    ) -> str:
        original = (original_text or "").strip()
        if not original:
            return original

        user_prompt = _build_user_prompt(
            original, role_name, role_character, brand_name, post_context
        )
        raw = await self._provider.generate(
            system=SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_prompt)],
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )
        text = _clean_output(raw)
        if not text:
            # LLM промолчал — безопаснее вернуть оригинал, чем пустую реплику.
            return original

        text = _enforce_max_len(text, original)
        text = _ensure_brand(text, brand_name)
        return text


# ── helpers ──────────────────────────────────────────────────────────────────


def _build_user_prompt(
    original: str,
    role_name: str,
    role_character: Optional[str],
    brand_name: Optional[str],
    post_context: Optional[str],
) -> str:
    lines = [f"Роль персонажа: {role_name}"]
    if role_character:
        lines.append(f"Характер/стиль речи: {role_character}")
    if brand_name:
        lines.append(f"Бренд (упомянуть дословно): {brand_name}")
    if post_context:
        lines.append(f"Контекст поста/чата: {post_context}")
    lines.append("")
    lines.append(f"Исходная реплика: «{original}»")
    return "\n".join(lines)


def _clean_output(raw: Optional[str]) -> str:
    text = (raw or "").strip()
    # Снимаем возможные обрамляющие кавычки, которые LLM иногда добавляет.
    if len(text) >= 2 and text[0] in "«\"'" and text[-1] in "»\"'":
        text = text[1:-1].strip()
    return text


def _enforce_max_len(text: str, original: str) -> str:
    budget = max(int(len(original) * _MAX_LEN_FACTOR), _MIN_LEN_BUDGET)
    if len(text) <= budget:
        return text
    # Обрезаем по границе слова, чтобы не рвать посреди слова.
    cut = text[:budget].rsplit(" ", 1)[0].rstrip()
    return cut or text[:budget]


def _ensure_brand(text: str, brand_name: Optional[str]) -> str:
    """Fallback-safety: если бренд потерялся в ответе — дописываем через тире."""
    if not brand_name:
        return text
    if brand_name.lower() in text.lower():
        return text
    return f"{text} — {brand_name}"
