"""Жизненный цикл ``TelegramClient`` внутри воркера (PROJECT-STAGES §3.1).

``ClientPool`` — единственный владелец инстансов ``TelegramClient`` в процессе
воркера. На один аккаунт приходится не более одного клиента (гарантируется
архитектурой одного worker-процесса, §6). Пул только управляет жизненным циклом
(создание / переиспользование / корректный disconnect) и НЕ вызывает методы
клиента (login, отправка, прослушивание) — это ответственность других модулей.

Клиент собирается строго из сохранённых полей аккаунта:

* ``StringSession`` — из ``accounts.session_enc`` через ``crypto.decrypt_session``;
* фингерпринт (``device_model``, ``system_version``, ``app_version``,
  ``lang_code``, ``system_lang_code``) — из записи аккаунта, НЕ дефолты Telethon
  (инвариант §0.3: фингерпринт иммутабелен и всегда явно передаётся);
* прокси — из привязанного ``accounts.proxy_id`` → ``proxies`` (пароль
  расшифровывается ``crypto.decrypt_password``).

Все аккаунты обязаны иметь прокси (инвариант §6): отсутствие ``proxy_id`` —
ошибка конфигурации, а не штатная ситуация.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Callable, ContextManager, Optional

from sqlalchemy.orm import Session
from telethon import TelegramClient
from telethon.sessions import StringSession

from core.config import Settings, get_settings
from core.crypto import decrypt_password, decrypt_session
from core.enums import AccountStatus
from core.repositories.account import AccountRepository
from core.repositories.proxy import ProxyRepository

# Фабрика сессий БД: вызывается без аргументов и возвращает контекст-менеджер,
# отдающий синхронную ``Session`` (та же форма, что у задач воркера).
SessionFactory = Callable[[], ContextManager[Session]]

# Фабрика клиента — точка подмены в тестах (реальный логин запрещён). Если не
# передана, используется модульный ``TelegramClient`` (его и патчат spy-моками).
ClientFactory = Callable[..., TelegramClient]

# Статусы, в которых аккаунт недоступен для работы и клиент не создаётся.
_UNAVAILABLE_STATUSES = frozenset(
    {AccountStatus.BANNED.value, AccountStatus.RETIRED.value}
)


class AccountUnavailableError(Exception):
    """Аккаунт нельзя использовать (не найден либо в статусе banned/retired)."""


@dataclass
class ManagedClient:
    """Учётная запись живого клиента в пуле: сам клиент и счётчик ссылок."""

    client: TelegramClient
    refcount: int = 0


class ClientPool:
    """Реестр долгоживущих ``TelegramClient`` с подсчётом ссылок.

    Потокобезопасность в рамках одного event loop обеспечивается ``asyncio.Lock``:
    создание и освобождение клиентов сериализуются, чтобы для одного аккаунта не
    возникло двух инстансов и не случилось гонки ``release`` против ``get``.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        settings: Optional[Settings] = None,
        client_factory: Optional[ClientFactory] = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._client_factory = client_factory
        self._clients: dict[int, ManagedClient] = {}
        self._lock = asyncio.Lock()

    async def get(self, account_id: int) -> TelegramClient:
        """Возвращает клиент для аккаунта, переиспользуя существующий.

        Повторный вызов для того же аккаунта отдаёт тот же инстанс и увеличивает
        счётчик ссылок. Для ``banned``/``retired`` (или отсутствующего) аккаунта
        бросает :class:`AccountUnavailableError`, клиент не создаётся.
        """
        async with self._lock:
            managed = self._clients.get(account_id)
            if managed is not None:
                managed.refcount += 1
                return managed.client

            client = self._create_client(account_id)
            self._clients[account_id] = ManagedClient(client=client, refcount=1)
            return client

    async def release(self, account_id: int) -> None:
        """Уменьшает счётчик ссылок; при нуле — disconnect и удаление из пула."""
        async with self._lock:
            managed = self._clients.get(account_id)
            if managed is None:
                return
            managed.refcount -= 1
            if managed.refcount <= 0:
                del self._clients[account_id]
                await self._disconnect(managed.client)

    async def close_all(self) -> None:
        """Graceful shutdown: дисконнектит все клиенты и очищает реестр."""
        async with self._lock:
            clients = [managed.client for managed in self._clients.values()]
            self._clients.clear()
            for client in clients:
                await self._disconnect(client)

    # --- внутреннее ---------------------------------------------------------

    def _create_client(self, account_id: int) -> TelegramClient:
        # Данные аккаунта и прокси читаем в короткоживущей сессии: сам клиент от
        # сессии БД не зависит.
        with self._session_factory() as session:
            account = AccountRepository(session).get(account_id)
            if account is None:
                raise AccountUnavailableError(f"account {account_id} not found")
            if account.status in _UNAVAILABLE_STATUSES:
                raise AccountUnavailableError(
                    f"account {account_id} is '{account.status}' and cannot be used"
                )

            if account.proxy_id is None:
                raise RuntimeError(
                    f"account {account_id} has no proxy_id; every account must be "
                    "bound to a proxy (invariant §6)"
                )
            proxy = ProxyRepository(session).get(account.proxy_id)
            if proxy is None:
                raise RuntimeError(
                    f"proxy {account.proxy_id} bound to account {account_id} "
                    "does not exist"
                )
            proxy_tuple = self._build_proxy(proxy)

            session_str = decrypt_session(account.session_enc).decode()

            settings = self._settings or get_settings()
            factory = self._client_factory or TelegramClient

            return factory(
                StringSession(session_str),
                settings.telegram_api_id,
                settings.telegram_api_hash,
                device_model=account.device_model,
                system_version=account.system_version,
                app_version=account.app_version,
                lang_code=account.lang_code,
                system_lang_code=account.system_lang_code,
                proxy=proxy_tuple,
                connection_retries=3,
                request_retries=3,
            )

    @staticmethod
    def _build_proxy(proxy) -> tuple:
        """Формат прокси для Telethon: (type, host, port, username, password)."""
        password = (
            decrypt_password(proxy.password_enc).decode()
            if proxy.password_enc is not None
            else None
        )
        return (proxy.type, proxy.host, proxy.port, proxy.login, password)

    @staticmethod
    async def _disconnect(client: TelegramClient) -> None:
        # ``disconnect`` у Telethon может быть как корутиной, так и синхронным
        # (в зависимости от состояния) — поддерживаем оба варианта.
        result = client.disconnect()
        if inspect.isawaitable(result):
            await result
