"""Юнит-тесты очистки токена Crypto Pay и диагностики 401.

Частая тихая причина UNAUTHORIZED — кавычки/пробелы в CRYPTOBOT_API_TOKEN из
.env, которые pydantic затягивает в значение. Проверяем, что заголовок уходит
очищенным и что сообщение об ошибке даёт полезную диагностику без утечки
секрета.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.billing.providers.cryptobot import (
    _clean_token,
    _describe_error,
    _token_diag,
)


def _settings(token: str, network: str = "testnet"):
    base = (
        "https://testnet-pay.crypt.bot/api"
        if network == "testnet"
        else "https://pay.crypt.bot/api"
    )
    return SimpleNamespace(
        cryptobot_api_token=token,
        cryptobot_network=network,
        cryptobot_base_url=base,
        cryptobot_asset="USDT",
    )


def test_clean_token_strips_quotes_and_spaces():
    assert _clean_token('"12345:ABCdef"') == "12345:ABCdef"
    assert _clean_token("  12345:ABCdef  ") == "12345:ABCdef"
    assert _clean_token("'12345:ABCdef'") == "12345:ABCdef"
    assert _clean_token("12345:ABCdef") == "12345:ABCdef"
    assert _clean_token(None) == ""
    assert _clean_token('""') == ""


def test_describe_error_401_adds_network_hint_and_diag():
    msg = _describe_error({"code": 401, "name": "UNAUTHORIZED"}, _settings('"12:AB"'))
    assert "testnet" in msg
    assert "testnet-pay.crypt.bot" in msg
    # Диагностика: кавычки были и их очистили; секрет не светится целиком.
    assert "кавычки" in msg
    assert '"12:AB"' not in msg


def test_token_diag_flags_missing_colon_and_empty():
    assert "нет ':'" in _token_diag(_settings("plaintextnocolon"))
    assert "пуст" in _token_diag(_settings("   "))
    # Нормальный токен — без тревожных пометок про двоеточие.
    assert "нет ':'" not in _token_diag(_settings("12345:ABCdef"))
