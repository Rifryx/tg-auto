"""Юнит-тесты разбора markdown первого поста в Telegram-entities."""

from __future__ import annotations

from modules.bulk.text_format import markdown_to_entities


def _kinds(entities):
    return [type(e).__name__ for e in entities]


def test_plain_text_no_entities():
    text, ents = markdown_to_entities("просто текст")
    assert text == "просто текст"
    assert ents == []


def test_bold_offset_and_length():
    text, ents = markdown_to_entities("привет **мир**")
    assert text == "привет мир"
    assert _kinds(ents) == ["MessageEntityBold"]
    assert ents[0].offset == 7  # len("привет ")
    assert ents[0].length == 3  # "мир"


def test_all_effects():
    text, ents = markdown_to_entities("**b** __i__ ~~s~~ ||sp|| `c`")
    assert text == "b i s sp c"
    assert _kinds(ents) == [
        "MessageEntityBold",
        "MessageEntityItalic",
        "MessageEntityStrike",
        "MessageEntitySpoiler",
        "MessageEntityCode",
    ]


def test_link_extracts_url():
    text, ents = markdown_to_entities("жми [сюда](https://t.me/x)")
    assert text == "жми сюда"
    assert _kinds(ents) == ["MessageEntityTextUrl"]
    assert ents[0].url == "https://t.me/x"
    assert ents[0].offset == 4
    assert ents[0].length == 4


def test_utf16_offsets_with_emoji():
    # 😀 занимает 2 единицы UTF-16 — смещение жирного должно это учесть.
    text, ents = markdown_to_entities("😀 **x**")
    assert text == "😀 x"
    assert ents[0].offset == 3  # emoji(2) + пробел(1)
    assert ents[0].length == 1


def test_unterminated_marker_is_literal():
    text, ents = markdown_to_entities("это **не закрыто")
    assert text == "это **не закрыто"
    assert ents == []


def test_empty_marker_pair_is_literal():
    text, ents = markdown_to_entities("пусто ****")
    assert text == "пусто ****"
    assert ents == []
