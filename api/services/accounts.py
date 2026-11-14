"""Сервисный слой аккаунтов: создание и листинг (PROJECT-STAGES §6/§10).

Здесь и только здесь собирается доменная операция создания аккаунта:
фингерпринт из :class:`FingerprintGenerator`, привязка прокси, пустая (ещё не
залогиненная) сессия. Постановка задачи ``account.login_start`` и смена статуса
происходят снаружи (роутер/очередь/state machine) — сервис БД-транзакцией
владеет, Telethon не трогает.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import get_settings
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


def _assert_owned_refs(
    session: Session,
    *,
    owner_user_id: Optional[str],
    proxy,
    persona_id: Optional[int],
) -> None:
    """Multi-tenancy: нельзя привязать к аккаунту чужой прокси/персону.

    Проверяем только когда владелец известен (``owner_user_id`` задан —
    пользовательский путь). Внутренние/тестовые вызовы без владельца
    пропускают проверку. ``proxy`` — уже загруженный объект (или None).
    """
    if owner_user_id is None:
        return
    if proxy is not None and proxy.user_id is not None and proxy.user_id != owner_user_id:
        raise ProxyNotFoundError(f"proxy {proxy.id} not found")
    if persona_id is not None:
        from core.repositories.persona import PersonaRepository

        persona = PersonaRepository(session).get(persona_id)
        if persona is not None and persona.user_id is not None and persona.user_id != owner_user_id:
            # 404-подобное поведение: для клиента персоны «не существует».
            raise ProxyNotFoundError(f"persona {persona_id} not found")


def list_accounts(
    session: Session,
    *,
    user_id: Optional[str] = None,
    status: Optional[AccountStatus] = None,
    warming_profile: Optional[WarmingProfile] = None,
    project_id: Optional[int] = None,
    role: Optional[str] = None,
    tag: Optional[str] = None,
) -> list[Account]:
    return AccountRepository(session).list_filtered(
        user_id=user_id,
        status=status,
        warming_profile=warming_profile,
        project_id=project_id,
        role=role,
        tag=tag,
    )


def create_account(
    session: Session,
    *,
    user_id: Optional[str] = None,
    phone: str,
    proxy_id: Optional[int],
    persona_id: Optional[int],
    warming_profile: WarmingProfile,
) -> Account:
    """Создаёт аккаунт (created) со сгенерированным фингерпринтом и прокси.

    ``proxy_id`` можно не задавать только при ``ALLOW_NO_PROXY=true`` (тесты без
    прокси); иначе прокси обязателен (инвариант §6).
    """
    phone = normalize_phone(phone)
    proxy = None
    if proxy_id is not None:
        proxy = ProxyRepository(session).get(proxy_id)
        if proxy is None:
            raise ProxyNotFoundError(f"proxy {proxy_id} not found")
    elif not get_settings().allow_no_proxy:
        raise ProxyNotFoundError(
            "proxy is required (set ALLOW_NO_PROXY=true to create without proxy)"
        )
    _assert_owned_refs(
        session, owner_user_id=user_id, proxy=proxy, persona_id=persona_id
    )

    accounts = AccountRepository(session)
    if accounts.get_by_phone(phone) is not None:
        raise PhoneAlreadyExistsError(phone)
    fingerprint = FingerprintGenerator(accounts).generate(proxy.geo if proxy else None)

    try:
        account = accounts.create(
            AccountCreate(
                phone=phone,
                user_id=user_id,
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


async def _tdata_dir_to_string(tdata_dir: str) -> tuple[str, Optional[int]]:
    """TData-папка → (StringSession, user_id) офлайн (opentele, UseCurrentSession).

    Сеть не нужна: auth_key и DC берутся прямо из tdata. PyQt5 (транзитивная
    зависимость opentele для разбора Qt-сериализации) импортируется лениво.

    Возвращает ``user_id`` из tdata — чтобы вызывающий код мог построить
    псевдо-телефон, если пользователь не ввёл настоящий номер (в tdata его нет,
    номер хранится только на серверах Telegram; получить его можно позже через
    ``get_me()`` при первом коннекте аккаунта).

    АСИНХРОННАЯ, потому что вызывает ``await tdesk.ToTelethon(...)``. Раньше
    тут был ``asyncio.run()`` — он падает ``RuntimeError`` при вызове из уже
    работающего event loop (напр. из FastAPI-handler'а), запрос зависал/рушился.
    """
    from opentele.api import UseCurrentSession
    from opentele.td import TDesktop
    from telethon.sessions import StringSession

    tdesk = TDesktop(tdata_dir)
    if not tdesk.isLoaded() or tdesk.accountsCount == 0:
        raise SessionImportError("tdata не содержит авторизованных аккаунтов")

    client = await tdesk.ToTelethon(flag=UseCurrentSession)
    string = StringSession.save(client.session)
    user_id: Optional[int] = None
    try:
        main = tdesk.mainAccount
        if main is not None:
            uid = main.UserId
            if isinstance(uid, int) and uid > 0:
                user_id = uid
    except Exception:  # noqa: BLE001 — user_id best-effort, не фатально
        user_id = None
    return string, user_id


def _extract_archive(archive_bytes: bytes, dest_dir: str) -> None:
    """Распаковывает ZIP или RAR-архив в ``dest_dir``.

    Формат определяется по содержимому (сигнатуре), а не по расширению. Для RAR
    нужен системный распаковщик (``unar``/``unrar``/``bsdtar``), который вызывает
    библиотека ``rarfile``; при его отсутствии — понятная ошибка."""
    import io
    import zipfile

    if zipfile.is_zipfile(io.BytesIO(archive_bytes)):
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
            zf.extractall(dest_dir)
        return

    # RAR: сигнатура "Rar!\x1a\x07".
    if archive_bytes[:4] == b"Rar!":
        try:
            import rarfile
        except ImportError as exc:  # pragma: no cover — зависит от окружения
            raise SessionImportError(
                "RAR-архивы не поддерживаются в этой сборке (нет пакета rarfile)"
            ) from exc
        try:
            with rarfile.RarFile(io.BytesIO(archive_bytes)) as rf:
                rf.extractall(dest_dir)
        except rarfile.RarCannotExec as exc:
            raise SessionImportError(
                "для RAR нужен системный распаковщик (unar/unrar). "
                "Загрузите tdata в ZIP."
            ) from exc
        return

    raise SessionImportError("файл не является ZIP или RAR-архивом")


async def tdata_archive_to_string(
    archive_bytes: bytes,
) -> tuple[str, Optional[int]]:
    """Конвертирует ZIP/RAR с папкой TData (Telegram Desktop) в StringSession.

    Возвращает ``(session_string, user_id?)``: ``user_id`` извлекается из tdata
    (лежит там рядом с auth_key), пригодится вызывающему коду для авто-заполнения
    псевдо-телефона, если пользователь не ввёл номер (в tdata телефона нет).

    Поддерживается только tdata без локального passcode-пароля (у защищённого
    ``isLoaded()`` вернёт False → понятная ошибка).
    """
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as d:
            _extract_archive(archive_bytes, d)
            tdata_dir = _find_tdata_dir(d)
            if tdata_dir is None:
                raise SessionImportError(
                    "в архиве не найдена папка tdata (нет файла key_datas)"
                )
            return await _tdata_dir_to_string(tdata_dir)
    except SessionImportError:
        raise
    except Exception as exc:  # noqa: BLE001 — любой сбой парсинга → понятная 422
        raise SessionImportError(f"не удалось разобрать tdata: {exc}") from exc


# Обратная совместимость: старое имя оставляем как асинхронный алиас.
async def tdata_zip_to_string(zip_bytes: bytes) -> tuple[str, Optional[int]]:
    return await tdata_archive_to_string(zip_bytes)


def pseudo_phone_from_session(session_string: str) -> str:
    """Детерминированный псевдо-номер из StringSession.

    StringSession хранит только dc_id/сервер/auth_key — настоящего номера
    в ней нет (узнать его можно лишь online через ``get_me()``). Пользователю
    он для импорта не нужен: подставляем хеш самой сессии как уникальный
    идентификатор в ``accounts.phone``. Детерминированность — бонус: повторный
    импорт той же .session-строки без номера корректно словит
    ``PhoneAlreadyExistsError`` вместо тихого дубликата в пуле.
    """
    digest = hashlib.sha256(session_string.encode()).hexdigest()[:16]
    return f"ses{digest}"


def import_account_from_session(
    session: Session,
    *,
    owner_user_id: Optional[str] = None,
    phone: str,
    proxy_id: Optional[int],
    persona_id: Optional[int],
    warming_profile: WarmingProfile,
    session_string: str,
    send_to_warming: bool = False,
) -> Account:
    """Создаёт аккаунт из готовой (авторизованной) StringSession.

    Сессия шифруется (``session_enc``); аккаунт либо сразу попадает в пул
    (``send_to_warming=False``, дефолт — как раньше), либо создаётся со
    статусом ``CREATED`` для последующего перехода в WARMING через
    state machine (``send_to_warming=True``). Логин по коду не нужен в
    обоих случаях — сессия уже авторизована.

    ``proxy_id`` можно опустить только при ``ALLOW_NO_PROXY=true`` (режим тестов
    без прокси) — как и при обычной регистрации по коду."""
    phone = normalize_phone(phone)
    proxy = None
    if proxy_id is not None:
        proxy = ProxyRepository(session).get(proxy_id)
        if proxy is None:
            raise ProxyNotFoundError(f"proxy {proxy_id} not found")
    elif not get_settings().allow_no_proxy:
        raise ProxyNotFoundError(
            "proxy is required (set ALLOW_NO_PROXY=true to import without proxy)"
        )
    _assert_owned_refs(
        session, owner_user_id=owner_user_id, proxy=proxy, persona_id=persona_id
    )

    accounts = AccountRepository(session)
    if accounts.get_by_phone(phone) is not None:
        raise PhoneAlreadyExistsError(phone)
    fingerprint = FingerprintGenerator(accounts).generate(proxy.geo if proxy else None)
    try:
        account = accounts.create(
            AccountCreate(
                phone=phone,
                user_id=owner_user_id,
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
        # Начальный статус зависит от send_to_warming:
        # * False (как раньше): импортированная сессия уже авторизована и
        #   «готова к бою» — сразу POOL;
        # * True: пользователь хочет сначала «обкатать» аккаунт нашим
        #   прогревом — оставляем CREATED, вызывающий код после enrichment
        #   сделает `WARMING_START` транзишн через state machine (как это
        #   делает обычный login-flow по коду, см. worker/login/flow.py).
        if send_to_warming:
            account.status = AccountStatus.CREATED.value
        else:
            account.status = AccountStatus.POOL.value
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _is_phone_unique_violation(exc):
            raise PhoneAlreadyExistsError(phone) from exc
        raise
    return account


def delete_account(session: Session, account_id: int) -> bool:
    """Полностью удаляет аккаунт (тонкая обёртка над AccountRepository.delete
    с коммитом — сама логика удаления живёт в core, т.к. ей пользуется и
    worker, которому api импортировать нельзя, см. core/repositories/account.py)."""
    ok = AccountRepository(session).delete(account_id)
    if ok:
        session.commit()
    return ok


class SessionNotAuthorizedError(Exception):
    """Session оказалась нерабочей: сервер отверг auth_key, аккаунт
    забанен/удалён, или прокси недоступен. Отличается от
    SessionImportError (той ловим на этапе чтения файла — до записи в БД).
    Специальный тип нужен чтобы в route вернуть понятную 422 вместо 500 и
    чтобы вызывающий код знал, что аккаунт в БД уже создан, надо откатить."""


# Имена Telethon-исключений, при которых сессия точно нерабочая и аккаунт
# надо откатить (а не оставить в БД в ожидании ручной починки). Другие
# ошибки (сеть, таймаут) — временные, их не трактуем как «невалидный
# session» и ОСТАВЛЯЕМ аккаунт в БД, пометив как pool (следующий
# sync_profile через UI-кнопку «Обновить» его дочитает).
_SESSION_FATAL_ERRORS = {
    "AuthKeyUnregisteredError",
    "AuthKeyInvalidError",
    "AuthKeyDuplicatedError",
    "SessionRevokedError",
    "SessionExpiredError",
    "UserDeactivatedError",
    "UserDeactivatedBanError",
    "PhoneNumberBannedError",
}


async def verify_and_enrich_session(
    session_factory,
    *,
    account_id: int,
    publisher=None,
) -> dict:
    """Проверяет живость только что импортированной session + подтягивает
    профиль (first_name/last_name/username/avatar/premium/2fa/bio).

    Делает это тем же путём, что и UI-кнопка «Обновить» в карточке
    аккаунта — вызывает ``sync_profile_impl`` из воркера. Без этого шага
    после импорта у пользователя был пустой профиль (имя «?», нет
    username, нет аватара, телефон = псевдо-хэш) и он не понимал,
    действительно ли сессия подключилась (баг-репорт «написало что
    аккаунт подключен, но ни одно поле не заполнено»).

    Поведение по ошибкам:
    * ``AuthKeyUnregisteredError`` / ``UserDeactivatedError`` и т.п. →
      удаляем созданный аккаунт из БД и бросаем SessionNotAuthorizedError —
      пользователь получает 422 вместо фантомной «успешной» записи.
    * Прочие ошибки (сеть, таймаут, прокси) — ОСТАВЛЯЕМ аккаунт в БД,
      только логируем. Пользователь увидит пустой профиль, но сможет
      нажать «Обновить» позже; удалять аккаунт за временный сбой сети
      жестоко."""
    from worker.profiles.sync import sync_profile_impl

    ctx = {"session_factory": session_factory, "publisher": publisher}
    try:
        await sync_profile_impl(ctx, account_id)
    except Exception as exc:  # noqa: BLE001 — разбираем ниже
        name = type(exc).__name__
        if name in _SESSION_FATAL_ERRORS:
            # Сессия точно нерабочая → откатываем аккаунт.
            with session_factory() as s:
                AccountRepository(s).delete(account_id)
                s.commit()
            raise SessionNotAuthorizedError(
                f"сессия не авторизована ({name}): аккаунт мог быть забанен, "
                "удалён или сессия отозвана. Проверьте, что .session-файл свежий."
            ) from exc
        # Временная ошибка — пусть аккаунт остаётся в БД, поле профиля
        # заполнятся при следующем «Обновить». Сигнализируем вызывающему,
        # чтобы он мог показать мягкое предупреждение, но не удалять.
        return {"verified": False, "error": repr(exc)}
    return {"verified": True}
