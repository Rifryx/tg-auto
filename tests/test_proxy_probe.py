"""Тесты реального хендшейка прокси (аудит #3).

HTTP-CONNECT проверяется против in-process мок-прокси; SOCKS5 — только если
установлен python-socks (в чистом CI-окружении установлен).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from worker.health.proxy_probe import probe_proxy

pytestmark = pytest.mark.asyncio


async def _mock_http_proxy(*, require_auth: bool):
    """Мок HTTP-прокси: 200 если (не требует auth) или пришёл Proxy-Authorization."""

    async def handle(reader, writer):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = await reader.read(1024)
            if not chunk:
                break
            data += chunk
        has_auth = b"proxy-authorization:" in data.lower()
        ok = (not require_auth) or has_auth
        resp = (
            b"HTTP/1.1 200 Connection established\r\n\r\n"
            if ok
            else b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"
        )
        writer.write(resp)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def test_http_proxy_alive_no_auth():
    server, port = await _mock_http_proxy(require_auth=False)
    try:
        proxy = SimpleNamespace(type="http", host="127.0.0.1", port=port, login=None, password_enc=None)
        alive = await probe_proxy(proxy, target=("example.com", 443), timeout=2.0)
        assert alive is True
    finally:
        server.close()
        await server.wait_closed()


async def test_http_proxy_alive_with_auth():
    server, port = await _mock_http_proxy(require_auth=True)
    try:
        # login задан → prober пошлёт Proxy-Authorization → мок ответит 200
        proxy = SimpleNamespace(type="http", host="127.0.0.1", port=port, login="user", password_enc=None)
        assert await probe_proxy(proxy, target=("example.com", 443), timeout=2.0) is True
    finally:
        server.close()
        await server.wait_closed()


async def test_http_proxy_dead_on_407():
    server, port = await _mock_http_proxy(require_auth=True)
    try:
        # auth требуется, но login=None → нет заголовка → 407 → мёртвый
        proxy = SimpleNamespace(type="http", host="127.0.0.1", port=port, login=None, password_enc=None)
        assert await probe_proxy(proxy, target=("example.com", 443), timeout=2.0) is False
    finally:
        server.close()
        await server.wait_closed()


async def test_connection_refused_is_dead():
    # порт, на котором никто не слушает (0 закрыт для connect) → False, без исключения
    proxy = SimpleNamespace(type="http", host="127.0.0.1", port=1, login=None, password_enc=None)
    assert await probe_proxy(proxy, target=("example.com", 443), timeout=1.0) is False


async def test_unknown_proxy_type_is_dead():
    proxy = SimpleNamespace(type="mystery", host="127.0.0.1", port=9, login=None, password_enc=None)
    assert await probe_proxy(proxy, target=("example.com", 443), timeout=1.0) is False


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("python_socks") is None,
    reason="python-socks не установлен в этом окружении",
)
async def test_socks5_dead_when_no_proxy_there():
    # нет SOCKS-прокси на этом порту → хендшейк не удастся → False (не исключение)
    proxy = SimpleNamespace(type="socks5", host="127.0.0.1", port=1, login=None, password_enc=None)
    assert await probe_proxy(proxy, target=("example.com", 443), timeout=1.0) is False
