"""Сервисный слой аккаунтов: создание и листинг (PROJECT-STAGES §6/§10).

Здесь и только здесь собирается доменная операция создания аккаунта:
фингерпринт из :class:`FingerprintGenerator`, привязка прокси, пустая (ещё не
залогиненная) сессия. Постановка задачи ``account.login_start`` и смена статуса
происходят снаружи (роутер/очередь/state machine) — сервис БД-транзакцией
владеет, Telethon не трогает.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.crypto import encrypt_session
from core.enums import AccountStatus, WarmingProfile
from core.models import Account
from core.repositories.account import AccountRepository
from core.repositories.proxy import ProxyRepository
from core.schemas.account import AccountCreate, AccountUpdate
from worker.fingerprint import FingerprintGenerator


def normalize_phone(phone: str) -> str:
    """Приводит номер к единому виду: убирает пробелы/скобки/дефисы и ставит
    ведущий «+» (как и обещает подсказка в UI — «+ добавится автоматически»).

    Единая нормализация на входе создания/импорта и в pre-check `check-phone`
    даёт консистентный ключ ``uq_accounts_phone`` — чтобы «такой номер уже
    есть» срабатывало детерминированно, а не зависело от формата ввода.
    """
    cleaned = re.sub(r"[\s()\-]", "", phone or "").strip()
    if not cleaned:
        return ""
    digits = cleaned.lstrip("+")
    if not digits.isdigit():
        # Нестандартный ввод не калечим — отдаём как есть (без пробелов).
        return cleaned
    return "+" + digits


class ProxyNotFoundError(Exception):
    """Указанный proxy_id не существует — аккаунт без прокси создавать нельзя."""


class PhoneAlreadyExistsError(Exception):
    """Телефон уже привязан к существующему аккаунту (uq_accounts_phone)."""

    def __init__(self, phone: str) -> None:
        super().__init__(f"phone {phone} already exists")
        self.phone = phone


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
    phone = normalize_phone(phone)
    proxy = ProxyRepository(session).get(proxy_id)
    if proxy is None:
        raise ProxyNotFoundError(f"proxy {proxy_id} not found")

    accounts = AccountRepository(session)
    if accounts.get_by_phone(phone) is not None:
        raise PhoneAlreadyExistsError(phone)
    fingerprint = FingerprintGenerator(accounts).generate(proxy.geo)

    try:
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
    except IntegrityError as exc:
        # Гонка: pre-check прошёл, но между get_by_phone и flush появился
        # дубликат (параллельный запрос). Откатываем, маппим в доменную ошибку.
        session.rollback()
        if _is_phone_unique_violation(exc):
            raise PhoneAlreadyExistsError(phone) from exc
        raise
    return account


def phone_exists(session: Session, phone: str) -> bool:
    """Есть ли уже аккаунт с таким (нормализованным) номером — для pre-check UI."""
    normalized = normalize_phone(phone)
    if not normalized:
        return False
    return AccountRepository(session).get_by_phone(normalized) is not None


def _is_phone_unique_violation(exc: IntegrityError) -> bool:
    text = str(exc.orig).lower() if exc.orig is not None else str(exc).lower()
    return "uq_accounts_phone" in text or "accounts_phone_key" in text


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


def _find_tdata_dir(root: str) -> Optional[str]:
    """Ищет внутри распакованного архива папку tdata (по файлу ``key_datas``)."""
    import os

    for dirpath, _dirnames, filenames in os.walk(root):
        if any(name.lower() == "key_datas" for name in filenames):
            return dirpath
    return None


def _tdata_dir_to_string(tdata_dir: str) -> str:
    """TData-папка → StringSession офлайн (opentele, flag=UseCurrentSession).

    Сеть не нужна: auth_key и DC берутся прямо из tdata. PyQt5 (транзитивная
    зависимость opentele для разбора Qt-сериализации) импортируется лениво."""
    import asyncio

    from opentele.api import UseCurrentSession
    from opentele.td import TDesktop
    from telethon.sessions import StringSession

    tdesk = TDesktop(tdata_dir)
    if not tdesk.isLoaded() or tdesk.accountsCount == 0:
        raise SessionImportError("tdata не содержит авторизованных аккаунтов")

    async def _convert() -> str:
        client = await tdesk.ToTelethon(flag=UseCurrentSession)
        return StringSession.save(client.session)

    return asyncio.run(_convert())


def tdata_zip_to_string(zip_bytes: bytes) -> str:
    """Конвертирует ZIP с папкой TData (Telegram Desktop) в StringSession.

    Поддерживается только tdata без локального passcode-пароля (у защищённого
    ``isLoaded()`` вернёт False → понятная ошибка)."""
    import io
    import tempfile
    import zipfile

    try:
        with tempfile.TemporaryDirectory() as d:
            try:
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    zf.extractall(d)
            except zipfile.BadZipFile as exc:
                raise SessionImportError("файл не является ZIP-архивом") from exc
            tdata_dir = _find_tdata_dir(d)
            if tdata_dir is None:
                raise SessionImportError(
                    "в архиве не найдена папка tdata (нет файла key_datas)"
                )
            return _tdata_dir_to_string(tdata_dir)
    except SessionImportError:
        raise
    except Exception as exc:  # noqa: BLE001 — любой сбой парсинга → понятная 422
        raise SessionImportError(f"не удалось разобрать tdata: {exc}") from exc


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
    phone = normalize_phone(phone)
    proxy = ProxyRepository(session).get(proxy_id)
    if proxy is None:
        raise ProxyNotFoundError(f"proxy {proxy_id} not found")

    accounts = AccountRepository(session)
    if accounts.get_by_phone(phone) is not None:
        raise PhoneAlreadyExistsError(phone)
    fingerprint = FingerprintGenerator(accounts).generate(proxy.geo)
    try:
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
    except IntegrityError as exc:
        session.rollback()
        if _is_phone_unique_violation(exc):
            raise PhoneAlreadyExistsError(phone) from exc
        raise
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
