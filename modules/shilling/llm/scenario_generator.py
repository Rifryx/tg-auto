"""Генератор сценариев шиллинга (docs/neuroshilling-spec.md § 6.2).

По теме, бренду и числу персон LLM собирает нативный диалог: роли + шаги
(кто, что говорит, кому отвечает). Результат НЕ пишется в БД — его отдаёт
эндпоинт ``POST /campaigns/{id}/scenario/generate``, а фронт решает, применять
ли (через ``PUT /campaigns/{id}/scenario`` + роли/шаги).

Провайдер (``worker.llm.LLMProvider``) инъектируется — тесты подставляют
FakeProvider.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from worker.llm.base import LLMProvider, Message


@dataclass
class GeneratedRole:
    name: str
    character: str = ""


@dataclass
class GeneratedStep:
    role: str  # имя роли (matchится к GeneratedRole.name)
    text: str
    reply_to_step: Optional[int] = None  # 1-based индекс шага, на который отвечает


@dataclass
class GeneratedScenario:
    roles: list[GeneratedRole] = field(default_factory=list)
    steps: list[GeneratedStep] = field(default_factory=list)
    raw: str = ""


class ScenarioGenerationError(RuntimeError):
    """LLM не вернул пригодный сценарий (пусто/битый JSON/нет валидных шагов)."""


SYSTEM_PROMPT = """
Ты — сценарист нативных диалогов для Telegram-чатов. Создай естественную
переписку между участниками так, чтобы это выглядело как живое обсуждение, а
не реклама.

Правила:
- Бренд упоминается ТОЛЬКО в ответах, НЕ в первом (наводящем) сообщении.
- Никаких ссылок (http, t.me), @-юзернеймов, хэштегов, явной рекламы.
- Стиль: живой разговор, неформальный; каждый участник говорит своим стилем.
- Первый шаг — вопрос/проблема от инициатора; далее ответы с органичным
  упоминанием бренда.

Верни СТРОГО JSON без пояснений в формате:
{
  "roles": [{"name": "Инициатор", "character": "спрашивает вежливо"}, ...],
  "steps": [
    {"role": "Инициатор", "text": "...", "reply_to_step": null},
    {"role": "Ответчик", "text": "...", "reply_to_step": 1}
  ]
}
reply_to_step — 1-based номер ПРЕДЫДУЩЕГО шага или null.
""".strip()

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")
# Сколько раз пытаемся, если бренд не попал ни в один шаг.
_MAX_ATTEMPTS = 2


class ScenarioGenerator:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_tokens: int = 900,
        temperature: float = 0.95,
    ) -> None:
        self._provider = provider
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def generate(
        self,
        *,
        topic: str,
        brand_name: str,
        persons_count: int = 2,
        steps_count: Optional[int] = None,
        roles: Optional[list[GeneratedRole]] = None,
    ) -> GeneratedScenario:
        if persons_count < 2:
            raise ScenarioGenerationError("persons_count must be >= 2")
        target_steps = steps_count or persons_count * 2

        last_error = ""
        for attempt in range(_MAX_ATTEMPTS):
            enforce_brand = attempt > 0  # на ретрае явно требуем бренд
            user_prompt = _build_user_prompt(
                topic, brand_name, persons_count, target_steps, roles, enforce_brand
            )
            raw = await self._provider.generate(
                system=SYSTEM_PROMPT,
                messages=[Message(role="user", content=user_prompt)],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
            )
            raw = (raw or "").strip()
            if not raw:
                last_error = "empty LLM response"
                continue

            try:
                scenario = _parse_and_validate(raw, brand_name, roles)
            except ScenarioGenerationError as exc:
                last_error = str(exc)
                # Если бренд просто не упомянут — есть смысл ретраить с enforce.
                if "brand" in last_error and attempt + 1 < _MAX_ATTEMPTS:
                    continue
                # Прочие ошибки (битый JSON, нет шагов) — ретраить бессмысленно.
                raise
            return scenario

        raise ScenarioGenerationError(last_error or "scenario generation failed")


# ── helpers ──────────────────────────────────────────────────────────────────


def _build_user_prompt(
    topic: str,
    brand_name: str,
    persons_count: int,
    steps_count: int,
    roles: Optional[list[GeneratedRole]],
    enforce_brand: bool,
) -> str:
    lines = [
        f"Тема обсуждения: {topic}",
        f"Бренд для упоминания: {brand_name}",
        f"Количество участников: {persons_count}",
        f"Примерное количество реплик: {steps_count}",
    ]
    if roles:
        role_desc = "; ".join(
            f"{r.name} ({r.character})" if r.character else r.name for r in roles
        )
        lines.append(f"Используй ИМЕННО эти роли: {role_desc}")
        lines.append("Поле roles в ответе продублируй этими же ролями.")
    else:
        lines.append("Роли придумай сам (по числу участников).")
    if enforce_brand:
        lines.append(
            f"ВАЖНО: бренд «{brand_name}» ОБЯЗАН дословно фигурировать хотя бы "
            "в одном из ответных шагов."
        )
    return "\n".join(lines)


def _parse_json(raw: str) -> dict:
    match = _JSON_BLOCK.search(raw)
    if match is None:
        raise ScenarioGenerationError(f"no JSON object in LLM response: {raw!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ScenarioGenerationError(f"invalid JSON from LLM: {exc}") from exc


def _parse_and_validate(
    raw: str,
    brand_name: str,
    forced_roles: Optional[list[GeneratedRole]],
) -> GeneratedScenario:
    data = _parse_json(raw)

    # Роли: либо форсированные, либо из ответа.
    if forced_roles:
        roles = list(forced_roles)
    else:
        roles = []
        for r in data.get("roles", []) or []:
            name = str(r.get("name", "")).strip() if isinstance(r, dict) else ""
            if name:
                roles.append(
                    GeneratedRole(
                        name=name,
                        character=str(r.get("character", "")).strip(),
                    )
                )
    if not roles:
        raise ScenarioGenerationError("no roles in scenario")

    role_names = {r.name for r in roles}

    # Шаги.
    raw_steps = data.get("steps", []) or []
    steps: list[GeneratedStep] = []
    for idx, s in enumerate(raw_steps, start=1):
        if not isinstance(s, dict):
            continue
        role = str(s.get("role", "")).strip()
        text = str(s.get("text", "")).strip()
        if not role or not text:
            continue
        if role not in role_names:
            raise ScenarioGenerationError(
                f"step {idx} references unknown role {role!r}"
            )
        reply_to = s.get("reply_to_step")
        if reply_to is not None:
            try:
                reply_to = int(reply_to)
            except (TypeError, ValueError):
                reply_to = None
            # reply_to должен указывать на предыдущий существующий шаг.
            if reply_to is not None and not (1 <= reply_to < idx):
                reply_to = None
        steps.append(GeneratedStep(role=role, text=text, reply_to_step=reply_to))

    if not steps:
        raise ScenarioGenerationError("no valid steps in scenario")

    # Бренд должен встречаться хотя бы в одном шаге.
    if brand_name and not any(brand_name.lower() in st.text.lower() for st in steps):
        raise ScenarioGenerationError("brand not mentioned in any step")

    return GeneratedScenario(roles=roles, steps=steps, raw=raw)
