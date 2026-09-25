"""Юнит-тесты генератора сценариев шиллинга. Без БД, без сети."""

from __future__ import annotations

import pytest

from modules.shilling.llm.scenario_generator import (
    GeneratedRole,
    ScenarioGenerationError,
    ScenarioGenerator,
)
from worker.llm.base import LLMProvider

pytestmark = pytest.mark.asyncio


class _FakeProvider(LLMProvider):
    """Отдаёт заранее заготовленные ответы по очереди (для ретраев)."""

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        self.calls.append(messages[0].content)
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


_GOOD = """
{
  "roles": [
    {"name": "Инициатор", "character": "спрашивает вежливо"},
    {"name": "Ответчик", "character": "делится опытом"}
  ],
  "steps": [
    {"role": "Инициатор", "text": "Посоветуйте салон в центре?", "reply_to_step": null},
    {"role": "Ответчик", "text": "Ходила в Beauty Zone, очень понравилось", "reply_to_step": 1}
  ]
}
"""


async def test_generate_parses_valid_scenario():
    gen = ScenarioGenerator(_FakeProvider(_GOOD))
    result = await gen.generate(topic="салоны", brand_name="Beauty Zone", persons_count=2)
    assert [r.name for r in result.roles] == ["Инициатор", "Ответчик"]
    assert len(result.steps) == 2
    assert result.steps[1].reply_to_step == 1
    assert "Beauty Zone" in result.steps[1].text


async def test_generate_rejects_unknown_role():
    bad = """
    {"roles": [{"name": "Инициатор"}],
     "steps": [{"role": "Кто-то", "text": "Beauty Zone топ", "reply_to_step": null}]}
    """
    gen = ScenarioGenerator(_FakeProvider(bad))
    with pytest.raises(ScenarioGenerationError, match="unknown role"):
        await gen.generate(topic="x", brand_name="Beauty Zone", persons_count=2)


async def test_generate_nullifies_forward_reply():
    # reply_to_step указывает вперёд (на шаг 2 из шага 1) → обнуляем.
    fwd = """
    {"roles": [{"name": "A"}, {"name": "B"}],
     "steps": [
       {"role": "A", "text": "вопрос", "reply_to_step": 2},
       {"role": "B", "text": "ответ про Brand", "reply_to_step": 1}
     ]}
    """
    gen = ScenarioGenerator(_FakeProvider(fwd))
    result = await gen.generate(topic="x", brand_name="Brand", persons_count=2)
    assert result.steps[0].reply_to_step is None
    assert result.steps[1].reply_to_step == 1


async def test_generate_retries_when_brand_missing_then_succeeds():
    no_brand = """
    {"roles": [{"name": "A"}, {"name": "B"}],
     "steps": [
       {"role": "A", "text": "вопрос", "reply_to_step": null},
       {"role": "B", "text": "просто ответ без бренда", "reply_to_step": 1}
     ]}
    """
    fake = _FakeProvider(no_brand, _GOOD)
    gen = ScenarioGenerator(fake)
    result = await gen.generate(topic="x", brand_name="Beauty Zone", persons_count=2)
    # второй ответ содержит бренд → успех, было 2 вызова (ретрай)
    assert len(fake.calls) == 2
    assert any("Beauty Zone" in s.text for s in result.steps)
    # на ретрае в промпт добавляется явное требование бренда
    assert "ОБЯЗАН" in fake.calls[1]


async def test_generate_raises_when_brand_never_appears():
    no_brand = """
    {"roles": [{"name": "A"}, {"name": "B"}],
     "steps": [{"role": "A", "text": "вопрос", "reply_to_step": null},
               {"role": "B", "text": "ответ без бренда", "reply_to_step": 1}]}
    """
    gen = ScenarioGenerator(_FakeProvider(no_brand, no_brand))
    with pytest.raises(ScenarioGenerationError, match="brand"):
        await gen.generate(topic="x", brand_name="Beauty Zone", persons_count=2)


async def test_generate_with_forced_roles_uses_them():
    steps_only = """
    {"steps": [
       {"role": "Скептик", "text": "а не развод ли?", "reply_to_step": null},
       {"role": "Эксперт", "text": "нет, Gram GPT реально работает", "reply_to_step": 1}
     ]}
    """
    gen = ScenarioGenerator(_FakeProvider(steps_only))
    roles = [GeneratedRole("Скептик", "сомневается"), GeneratedRole("Эксперт", "уверенный")]
    result = await gen.generate(
        topic="сервисы", brand_name="Gram GPT", persons_count=2, roles=roles
    )
    assert [r.name for r in result.roles] == ["Скептик", "Эксперт"]
    assert len(result.steps) == 2


async def test_generate_raises_on_broken_json():
    gen = ScenarioGenerator(_FakeProvider("это не json совсем"))
    with pytest.raises(ScenarioGenerationError):
        await gen.generate(topic="x", brand_name="B", persons_count=2)


async def test_generate_rejects_persons_count_below_two():
    gen = ScenarioGenerator(_FakeProvider(_GOOD))
    with pytest.raises(ScenarioGenerationError, match="persons_count"):
        await gen.generate(topic="x", brand_name="B", persons_count=1)
