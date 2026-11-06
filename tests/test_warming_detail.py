"""warming_detail: описания действий прогрева для ленты «Активность».

Главное требование — единый язык: никаких английских слов посреди русской
фразы (баг-репорт показал «искал peer», «не удалось (unknown)»). Эвристика:
в тексте не должно быть латиницы, КРОМЕ самой цели (@username, t.me/...),
которую подставляет пользователь.
"""

from __future__ import annotations

import re

import pytest

from core.warming_detail import warming_detail

# Латиница допустима только внутри @handle / ссылки — вырезаем их, остальное
# должно быть кириллицей/цифрами/пунктуацией.
_HANDLE = re.compile(r"(@[\w\d_]+|https?://\S+|t\.me/\S+)")


def _no_latin_outside_handle(text: str) -> bool:
    stripped = _HANDLE.sub("", text)
    return not re.search(r"[A-Za-z]", stripped)


@pytest.mark.parametrize(
    "action,target,meta,status",
    [
        ("interact_with_peer", None, None, None),
        ("interact_with_peer", "user_ams3", {"reacted": True}, None),
        ("read_history", "telegram", {"read": 20}, None),
        ("view_media", "durov", {"viewed": 7}, None),
        ("reaction", "durov", {"emoji": "🔥"}, None),
        ("subscribe_channel", "ainews", None, None),
        ("join_group", "pythonru", None, None),
        ("idle_online", None, None, None),
        ("update_profile", None, {"field": "bio"}, None),
        ("subscribe_channel", "durov", {"error_category": "unknown"}, "failed"),
        ("reaction", "durov", {"error_category": "rate_limit"}, "failed"),
        ("read_history", "x", {"error_category": "target_broken"}, "failed"),
        ("join_group", "x", {"error_category": "fatal"}, "failed"),
        ("idle_online", None, None, "skipped"),
    ],
)
def test_warming_detail_is_fully_russian(action, target, meta, status):
    text = warming_detail(action, target=target, meta=meta, status=status)
    assert text, "описание не должно быть пустым"
    assert _no_latin_outside_handle(text), f"английские слова в «{text}»"


def test_failed_shows_russian_reason_not_code():
    assert warming_detail(
        "idle_online", status="failed", meta={"error_category": "unknown"}
    ) == "не удалось: неизвестная ошибка"
    # Неизвестный код не роняет, падает в «ошибка».
    assert warming_detail(
        "idle_online", status="failed", meta={"error_category": "weird_code"}
    ) == "не удалось: ошибка"


def test_peer_wording_is_gone():
    out = warming_detail("interact_with_peer", target=None)
    assert "peer" not in out.lower()
    assert out == "искал аккаунт для общения"
