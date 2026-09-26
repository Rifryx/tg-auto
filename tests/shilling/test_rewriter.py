"""Юнит-тесты рерайтера реплик шиллинга. Без БД, без сети."""

from __future__ import annotations

import pytest

from modules.shilling.llm.rewriter import (
    ReplicaRewriter,
    _enforce_max_len,
    _ensure_brand,
)
from worker.llm.base import LLMProvider

pytestmark = pytest.mark.asyncio


class _FakeProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, list]] = []

    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        self.calls.append((system, list(messages)))
        return self.response


async def test_rewrite_returns_cleaned_text():
    rw = ReplicaRewriter(_FakeProvider('«Была в Beauty Zone, всё супер»'))
    out = await rw.rewrite(
        "Я ходила в Beauty Zone, понравилось",
        role_name="Ответчик",
        brand_name="Beauty Zone",
    )
    # обрамляющие кавычки сняты, бренд на месте
    assert out == "Была в Beauty Zone, всё супер"


async def test_rewrite_preserves_brand_via_fallback():
    # LLM «забыл» бренд — дописываем через тире.
    rw = ReplicaRewriter(_FakeProvider("Отличный сервис, рекомендую"))
    out = await rw.rewrite(
        "Beauty Zone топ", role_name="Ответчик", brand_name="Beauty Zone"
    )
    assert "Beauty Zone" in out
    assert out.endswith("— Beauty Zone")


async def test_rewrite_brand_case_insensitive_no_double_append():
    rw = ReplicaRewriter(_FakeProvider("ходил в beauty zone, ок"))
    out = await rw.rewrite(
        "Beauty Zone класс", role_name="Ответчик", brand_name="Beauty Zone"
    )
    # бренд присутствует (в другом регистре) — второй раз не дописываем
    assert out.count("eauty") == 1


async def test_rewrite_empty_original_returns_empty():
    rw = ReplicaRewriter(_FakeProvider("что-то"))
    assert await rw.rewrite("   ", role_name="Инициатор") == ""


async def test_rewrite_empty_llm_falls_back_to_original():
    rw = ReplicaRewriter(_FakeProvider("   "))
    out = await rw.rewrite("Оригинал реплики", role_name="Инициатор")
    assert out == "Оригинал реплики"


async def test_rewrite_passes_context_into_prompt():
    fake = _FakeProvider("ok")
    rw = ReplicaRewriter(fake)
    await rw.rewrite(
        "текст",
        role_name="Скептик",
        role_character="сомневается во всём",
        brand_name="Gram GPT",
        post_context="обсуждают сервисы аналитики",
    )
    system, messages = fake.calls[0]
    user = messages[0].content
    assert "Скептик" in user
    assert "сомневается во всём" in user
    assert "Gram GPT" in user
    assert "аналитики" in user


def test_enforce_max_len_trims_on_word_boundary():
    original = "короткая"  # 8 симв → budget = max(12, 40) = 40
    long = "это очень длинная переписанная реплика намного больше сорока символов точно"
    out = _enforce_max_len(long, original)
    assert len(out) <= 40
    assert not out.endswith(" ")  # обрезка по границе слова


def test_ensure_brand_noop_when_no_brand():
    assert _ensure_brand("любой текст", None) == "любой текст"
