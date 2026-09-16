"""Юнит-тесты генератора профилей (этап 6 УТП). Без БД, без сети."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.profiles.generator import (
    NAME_MAX,
    ProfileGenerationError,
    ProfileGenerator,
    USERNAME_RE,
    _clean_username,
    _parse_response,
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


def _persona(**overrides):
    base = SimpleNamespace(
        id=1,
        name="Разработчик Никита",
        personality_tags=["ru", "casual"],
        bio_template="Пишет коротко, любит горные лыжи",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


# ── json path ────────────────────────────────────────────────────────────────


async def test_generator_parses_strict_json():
    resp = """
    {
      "first_name": "Никита",
      "last_name": "Ковалёв",
      "bio": "code · ski · long walks",
      "username_candidates": ["nick_ski", "kovalev_dev", "n1kita_c"]
    }
    """
    gen = ProfileGenerator(_FakeProvider(resp))
    result = await gen.generate(_persona())
    assert result.first_name == "Никита"
    assert result.last_name == "Ковалёв"
    assert result.bio == "code · ski · long walks"
    assert result.username_candidates == ["nick_ski", "kovalev_dev", "n1kita_c"]


async def test_generator_clips_long_fields():
    long_name = "A" * (NAME_MAX + 30)
    long_bio = "B" * 200
    resp = f'{{"first_name":"{long_name}","last_name":"","bio":"{long_bio}","username_candidates":["okname1"]}}'
    result = await ProfileGenerator(_FakeProvider(resp)).generate(_persona())
    assert len(result.first_name) == NAME_MAX
    assert len(result.bio) == 70  # BIO_MAX


async def test_generator_rejects_bad_usernames():
    resp = (
        '{"first_name":"N","last_name":"K","bio":"b",'
        '"username_candidates":["ok_name","1badstart","!!!","@nick_dev"]}'
    )
    result = await ProfileGenerator(_FakeProvider(resp)).generate(_persona())
    # 1badstart отфильтрован (не с буквы), !!! пуст после чистки, @nick_dev → nick_dev.
    assert result.username_candidates == ["ok_name", "nick_dev"]


async def test_generator_raises_on_missing_first_name():
    resp = '{"first_name":"","last_name":"K","bio":"b","username_candidates":[]}'
    with pytest.raises(ProfileGenerationError):
        await ProfileGenerator(_FakeProvider(resp)).generate(_persona())


async def test_generator_raises_on_empty_llm_response():
    with pytest.raises(ProfileGenerationError):
        await ProfileGenerator(_FakeProvider("")).generate(_persona())


# ── fallback: ключ-значение без JSON ─────────────────────────────────────────


async def test_generator_uses_fallback_when_json_broken():
    # Битый JSON: незакрытая скобка. Парсер должен вытянуть поля построчно.
    resp = """
    first_name: Никита
    last_name: Ковалёв
    bio: краткое описание
    username_candidates: [nick_dev, ski_lover, kv_dev]
    """
    result = await ProfileGenerator(_FakeProvider(resp)).generate(_persona())
    assert result.first_name == "Никита"
    assert result.last_name == "Ковалёв"
    assert result.bio == "краткое описание"
    assert set(result.username_candidates) == {"nick_dev", "ski_lover", "kv_dev"}


# ── чистая утилита _clean_username ────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_clean_username_strips_prefixes_and_bad_chars():
    # Sync-логика, но чтобы не спорить с global pytestmark — оборачиваем.
    assert _clean_username("@Nick_Dev") == "Nick_Dev"
    assert _clean_username("https://t.me/foo_bar") == "foo_bar"
    assert _clean_username("bad name!!!") == "badname"
    assert len(_clean_username("A" * 100)) == 32


@pytest.mark.asyncio(loop_scope="function")
async def test_username_regex_matches_valid():
    assert USERNAME_RE.match("Alice_1")
    assert not USERNAME_RE.match("1nvalid")  # начинается с цифры
    assert not USERNAME_RE.match("abcd")     # <5 символов


# ── персона → prompt ──────────────────────────────────────────────────────────


async def test_generator_includes_persona_tags_in_prompt():
    fp = _FakeProvider(
        '{"first_name":"N","last_name":"","bio":"","username_candidates":["nick_dev"]}'
    )
    gen = ProfileGenerator(fp)
    persona = _persona(name="Trader", personality_tags=["en", "formal"], bio_template=None)
    await gen.generate(persona)
    system, messages = fp.calls[0]
    prompt = messages[0].content
    assert "Trader" in prompt
    assert "en" in prompt and "formal" in prompt
