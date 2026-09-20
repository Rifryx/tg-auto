"""Сервисный слой аккаунтов: создание и листинг (PROJECT-STAGES §6/§10).

Здесь и только здесь собирается доменная операция создания аккаунта:
фингерпринт из :class:`FingerprintGenerator`, привязка прокси, пустая (ещё не
залогиненная) сессия. Постановка задачи ``account.login_start`` и смена статуса
происходят снаружи (роутер/очередь/state machine) — сервис БД-транзакцией
владеет, Telethon не трогает.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from core.crypto import encrypt_session
from core.enums import AccountStatus, WarmingProfile
from core.models import Account
from core.repositories.account import AccountRepository
from core.repositories.proxy import ProxyRepository
from core.schemas.account import AccountCreate, AccountUpdate
from worker.fingerprint import FingerprintGenerator


class ProxyNotFoundError(Exception):
    """Указанный proxy_id не существует — аккаунт без прокси создавать нельзя."""


def list_accounts(
    session: Session,
    *,
    status: Optional[AccountStatus] = None,
    warming_profile: Optional[WarmingProfile] = None,
    project_id: Optional[int] = None,
    role: Optional[str] = None,
    tag: Optional[str] = None,
) -> list[Account]:
    return AccountRepository(session).list_filtered(
        status=status,
        warming_profile=warming_profile,
        project_id=project_id,
        role=role,
        tag=tag,
    )


def create_account(
    session: Session,
    *,
    phone: str,
    proxy_id: int,
    persona_id: Optional[int],
    warming_profile: WarmingProfile,
) -> Account:
    """Создаёт аккаунт (created) со сгенерированным фингерпринтом и прокси."""
    proxy = ProxyRepository(session).get(proxy_id)
    if proxy is None:
        raise ProxyNotFoundError(f"proxy {proxy_id} not found")

    accounts = AccountRepository(session)
    fingerprint = FingerprintGenerator(accounts).generate(proxy.geo)

    account = accounts.create(
        AccountCreate(
            phone=phone,
            # Пустая StringSession: заполнится логин-флоу после ввода кода.
            session_enc=encrypt_session(b""),
            proxy_id=proxy_id,
            persona_id=persona_id,
            warming_profile=warming_profile,
            device_model=fingerprint.device_model,
            system_version=fingerprint.system_version,
            app_version=fingerprint.app_version,
            lang_code=fingerprint.lang_code,
            system_lang_code=fingerprint.system_lang_code,
        )
    )
    session.commit()
    return account


def update_account(session: Session, account_id: int, data: AccountUpdate) -> Optional[Account]:
    account = AccountRepository(session).update(account_id, data)
    if account is not None:
        session.commit()
    return account


class SessionImportError(Exception):
    """Не удалось разобрать переданную сессию (строка/файл повреждены)."""


def session_file_to_string(file_bytes: bytes) -> str:
    """Конвертирует Telethon ``.session`` (SQLite) в StringSession — офлайн,
    без сети и api_id (читаем auth_key/dc локально)."""
    import os
    import tempfile

    from telethon.sessions import SQLiteSession, StringSession

    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "import")
        with open(base + ".session", "wb") as f:
            f.write(file_bytes)
        sqlite = SQLiteSession(base)
        try:
            if sqlite.auth_key is None:
                raise SessionImportError("session-файл без auth_key (не авторизован)")
            return StringSession.save(sqlite)
        finally:
            sqlite.close()


def import_account_from_session(
    session: Session,
    *,
    phone: str,
    proxy_id: int,
    persona_id: Optional[int],
    warming_profile: WarmingProfile,
    session_string: str,
) -> Account:
    """Создаёт аккаунт из готовой (авторизованной) StringSession.

    Сессия шифруется (``session_enc``); аккаунт сразу попадает в пул — логин по
    коду не нужен. Валидность сессии проверит воркер при первом использовании."""
    proxy = ProxyRepository(session).get(proxy_id)
    if proxy is None:
        raise ProxyNotFoundError(f"proxy {proxy_id} not found")

    accounts = AccountRepository(session)
    fingerprint = FingerprintGenerator(accounts).generate(proxy.geo)
    account = accounts.create(
        AccountCreate(
            phone=phone,
            session_enc=encrypt_session(session_string.encode()),
            proxy_id=proxy_id,
            persona_id=persona_id,
            warming_profile=warming_profile,
            device_model=fingerprint.device_model,
            system_version=fingerprint.system_version,
            app_version=fingerprint.app_version,
            lang_code=fingerprint.lang_code,
            system_lang_code=fingerprint.system_lang_code,
        )
    )
    # Импортированная сессия уже авторизована → начальный статус «в пуле».
    account.status = AccountStatus.POOL.value
    session.commit()
    return account


def delete_account(session: Session, account_id: int) -> bool:
    """Полностью удаляет аккаунт. Зависимые строки (история, health, прогрев,
    каналы, привязка к кампании, логи) снимаются через ON DELETE CASCADE."""
    account = AccountRepository(session).get(account_id)
    if account is None:
        return False
    session.delete(account)
    session.commit()
    return True
