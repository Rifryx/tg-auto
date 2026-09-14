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
) -> list[Account]:
    repo = AccountRepository(session)
    if status is not None:
        accounts = repo.list_by_status(status)
    else:
        accounts = repo.list_all()
    if warming_profile is not None:
        wp = WarmingProfile(warming_profile).value
        accounts = [a for a in accounts if a.warming_profile == wp]
    return accounts


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


def delete_account(session: Session, account_id: int) -> bool:
    """Полностью удаляет аккаунт. Зависимые строки (история, health, прогрев,
    каналы, привязка к кампании, логи) снимаются через ON DELETE CASCADE."""
    account = AccountRepository(session).get(account_id)
    if account is None:
        return False
    session.delete(account)
    session.commit()
    return True
