"""Реальный хендшейк проверки прокси (PROJECT-STAGES §5.3; аудит #3).

Раньше health.check_proxies делал простой TCP-connect (liveness) — он не
доказывал, что прокси реально проксирует и что авторизация валидна. Здесь —
настоящий хендшейк по типу прокси до целевого хоста (``proxy_check_*`` в конфиге):

* ``socks5``/``socks4`` — через ``python-socks`` (greeting + auth + CONNECT);
* ``http`` — ``CONNECT host:port`` c ``Proxy-Authorization: Basic`` и ожиданием
  ``HTTP/1.1 200``.

Любая ошибка/таймаут/не-200 → прокси считается мёртвым (False). Наружу
исключения не пробрасываются — это health-проба, а не рабочий вызов.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Optional, Tuple

import structlog

from core.crypto import decrypt_password

# structlog напрямую (а не worker.tasks.logging), иначе цикл:
# worker.tasks.health → proxy_probe → worker.tasks.logging → worker.tasks(init).
get_logger = structlog.get_logger

_DEFAULT_TIMEOUT = 5.0


def _credentials(proxy: Any) -> Tuple[Optional[str], Optional[str]]:
    login = getattr(proxy, "login", None)
    password_enc = getattr(proxy, "password_enc", None)
    password = decrypt_password(password_enc).decode() if password_enc else None
    return login, password


async def _http_connect(
    host: str,
    port: int,
    login: Optional[str],
    password: Optional[str],
    target: Tuple[str, int],
    timeout: float,
) -> bool:
    target_hostport = f"{target[0]}:{target[1]}"
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout
    )
    try:
        req = f"CONNECT {target_hostport} HTTP/1.1\r\nHost: {target_hostport}\r\n"
        if login is not None:
            token = base64.b64encode(f"{login}:{password or ''}".encode()).decode()
            req += f"Proxy-Authorization: Basic {token}\r\n"
        req += "\r\n"
        writer.write(req.encode())
        await writer.drain()
        status_line = await asyncio.wait_for(reader.readline(), timeout)
        parts = status_line.decode(errors="replace").split()
        # "HTTP/1.1 200 Connection established"
        return len(parts) >= 2 and parts[1] == "200"
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


async def _socks_connect(
    proxy_type: str,
    host: str,
    port: int,
    login: Optional[str],
    password: Optional[str],
    target: Tuple[str, int],
    timeout: float,
) -> bool:
    # Ленивый импорт: python-socks нужен только для socks-прокси.
    from python_socks import ProxyType
    from python_socks.async_.asyncio import Proxy

    ptype = ProxyType.SOCKS5 if proxy_type == "socks5" else ProxyType.SOCKS4
    proxy = Proxy(
        proxy_type=ptype,
        host=host,
        port=port,
        username=login,
        password=password,
    )
    sock = await asyncio.wait_for(
        proxy.connect(dest_host=target[0], dest_port=target[1]), timeout
    )
    try:
        return True
    finally:
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass


async def probe_proxy(
    proxy: Any,
    *,
    target: Tuple[str, int],
    timeout: float = _DEFAULT_TIMEOUT,
) -> bool:
    """Реальный хендшейк до ``target`` через ``proxy``. True — прокси рабочий."""
    ptype = getattr(proxy, "type", None)
    host, port = proxy.host, proxy.port
    login, password = _credentials(proxy)
    try:
        if ptype in ("socks5", "socks4"):
            return await _socks_connect(ptype, host, port, login, password, target, timeout)
        if ptype == "http":
            return await _http_connect(host, port, login, password, target, timeout)
        get_logger().warning("health.proxy_probe.unknown_type", proxy_type=ptype)
        return False
    except Exception as exc:  # noqa: BLE001 - проба не должна ронять cron
        get_logger().info(
            "health.proxy_probe.failed",
            proxy_id=getattr(proxy, "id", None),
            proxy_type=ptype,
            error=repr(exc),
        )
        return False
