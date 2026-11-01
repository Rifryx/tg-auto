"""Тесты LLM-адаптеров и StyleRandomizer (PROJECT-STAGES §7).

Сеть не трогаем: DeepSeek — мок httpx-клиента, Gemini — инъекция model.
Randomizer — чистые функции; распределения проверяются на seeded RNG.
"""

from __future__ import annotations

import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from core.config import get_settings
from worker.llm import (
    DeepSeekProvider,
    GeminiProvider,
    Message,
    OpenAICompatProvider,
    StyleRandomizer,
    get_provider,
    reset_cache,
)
from worker.llm import style as style_mod


@pytest.fixture(autouse=True)
def _reset_factory(monkeypatch):
    # factory инстанцирует провайдеры → они читают ключи из core.config.
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    reset_cache()
    yield
    reset_cache()
    get_settings.cache_clear()


# --- 1. DeepSeek -------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepseek_generate_returns_content():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(
        return_value={"choices": [{"message": {"content": "привет из deepseek"}}]}
    )
    client = MagicMock()
    client.post = AsyncMock(return_value=response)

    provider = DeepSeekProvider(api_key="k", client=client)
    out = await provider.generate("sys", [Message("user", "hi")], max_tokens=50)

    assert out == "привет из deepseek"
    # проверим, что system + сообщение ушли в payload
    _, kwargs = client.post.call_args
    roles = [m["role"] for m in kwargs["json"]["messages"]]
    assert roles == ["system", "user"]
    assert kwargs["json"]["max_tokens"] == 50


# --- 2. Gemini ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_generate_returns_text():
    model = MagicMock()
    model.generate_content_async = AsyncMock(return_value=SimpleNamespace(text="ответ gemini"))

    provider = GeminiProvider(api_key="k", model=model)
    out = await provider.generate("sys", [Message("user", "hi")])

    assert out == "ответ gemini"
    model.generate_content_async.assert_awaited_once()


# --- 3. factory --------------------------------------------------------------


def test_factory_maps_and_caches():
    assert isinstance(get_provider("deepseek"), DeepSeekProvider)
    assert isinstance(get_provider("gemini"), GeminiProvider)
    # кэш: тот же инстанс
    assert get_provider("deepseek") is get_provider("deepseek")
    with pytest.raises(ValueError):
        get_provider("openai")


# --- 3b. AnyModel: единый ключ маршрутизирует оба имени ----------------------


@pytest.mark.asyncio
async def test_openai_compat_generate_returns_content():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(
        return_value={"choices": [{"message": {"content": "привет из anymodel"}}]}
    )
    client = MagicMock()
    client.post = AsyncMock(return_value=response)

    provider = OpenAICompatProvider(
        "k", base_url="https://anymodel.org/v1/", model="ds/deepseek-v4-flash", client=client
    )
    out = await provider.generate("sys", [Message("user", "hi")], max_tokens=50)

    assert out == "привет из anymodel"
    args, kwargs = client.post.call_args
    # базовый URL без хвостового слэша + /chat/completions
    assert args[0] == "https://anymodel.org/v1/chat/completions"
    assert kwargs["json"]["model"] == "ds/deepseek-v4-flash"
    roles = [m["role"] for m in kwargs["json"]["messages"]]
    assert roles == ["system", "user"]
    assert kwargs["headers"]["Authorization"] == "Bearer k"


def test_factory_routes_through_anymodel_when_key_set(monkeypatch):
    monkeypatch.setenv("ANYMODEL_API_KEY", "any-key")
    monkeypatch.setenv("ANYMODEL_MODEL_DEEPSEEK", "ds/deepseek-v4-flash")
    monkeypatch.setenv("ANYMODEL_MODEL_GEMINI", "ag/gemini-3.1-flash-lite-preview")
    get_settings.cache_clear()
    reset_cache()

    ds = get_provider("deepseek")
    gm = get_provider("gemini")

    # оба имени → OpenAICompatProvider с единым ключом/URL, разными model id
    assert isinstance(ds, OpenAICompatProvider)
    assert isinstance(gm, OpenAICompatProvider)
    assert ds._model == "ds/deepseek-v4-flash"
    assert gm._model == "ag/gemini-3.1-flash-lite-preview"
    assert ds._api_key == gm._api_key == "any-key"
    assert ds._base_url == "https://anymodel.org/v1"
    # кэш: тот же инстанс
    assert get_provider("deepseek") is ds


# --- 3c. Правило «выводи сразу готовый текст» --------------------------------


def test_with_direct_output_appends_rule():
    from worker.llm import with_direct_output

    out = with_direct_output("Ты — читатель канала.")
    assert out.startswith("Ты — читатель канала.")
    # Ключевой запрет: без «вот несколько вариантов».
    assert "вариант" in out.lower()
    assert "СРАЗУ готовый текст" in out


# --- 4. randomizer детерминирован --------------------------------------------


def test_randomizer_deterministic_with_seed():
    text = "Hello world. This is a sentence. And another one."
    a = StyleRandomizer(random.Random(1234)).randomize(text)
    b = StyleRandomizer(random.Random(1234)).randomize(text)
    assert a == b


# --- 5. распределение ~ константам (±5%) -------------------------------------


def _rate(p_kwarg: str, prob: float, text: str, runs: int = 2000) -> float:
    rng = random.Random(2024)
    changed = 0
    for _ in range(runs):
        r = StyleRandomizer(
            rng, **{"p_shorten": 0.0, "p_emoji": 0.0, "p_typo": 0.0, "p_case": 0.0, p_kwarg: prob}
        )
        out = r.randomize(text)
        if out != text:
            changed += 1
    return changed / runs


def test_probability_distribution_matches_constants():
    # каждое правило измеряется в изоляции (остальные отключены)
    assert abs(_rate("p_shorten", style_mod.P_SHORTEN, "One two three. Four five six. Seven.") - style_mod.P_SHORTEN) <= 0.05
    assert abs(_rate("p_emoji", style_mod.P_EMOJI, "just some plain text") - style_mod.P_EMOJI) <= 0.05
    assert abs(_rate("p_typo", style_mod.P_TYPO, "warming words matter here") - style_mod.P_TYPO) <= 0.05
    assert abs(_rate("p_case", style_mod.P_CASE, "Sentence ends here.") - style_mod.P_CASE) <= 0.05


# --- 6. formal persona → без опечаток ----------------------------------------


def test_formal_persona_no_typos():
    persona = SimpleNamespace(personality_tags=["formal"])
    text = "warming words matter here"
    # включаем ТОЛЬКО опечатки; formal обнуляет их вероятность
    r = StyleRandomizer(
        random.Random(7), p_shorten=0.0, p_emoji=0.0, p_typo=style_mod.P_TYPO, p_case=0.0
    )
    for _ in range(100):
        assert r.randomize(text, persona) == text
