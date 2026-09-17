"""Логин-флоу Telegram-аккаунта целиком в воркере (PROJECT-STAGES §3.2 / §11).

Три arq-задачи (``account.login_start`` / ``login_confirm`` / ``login_password``)
проводят аккаунт через вход по коду и, при необходимости, 2FA. Клиент берётся из
:class:`ClientPool` (единственный владелец ``TelegramClient``); эфемерное
состояние между шагами (``phone_code_hash``) хранится в ``accounts.meta``.

Границы ответственности:
* смена статуса — ТОЛЬКО через :class:`AccountStateMachine` (событие
  ``warming.start``: created → warming). Сразу после перехода первичный прогрев
  запускается постановкой задачи ``warming.initial_start`` в очередь через
  :class:`TaskQueue` (единый транспорт — не прямым импортом функции прогрева).
* ``FloodWaitError`` от Telethon превращается в диспетчерский
  :class:`worker.tasks.dispatch.FloodWaitError` — его ловит middleware и делает
  отложенный ретрай (провалом это НЕ считается).
* все события шага публикуются в pub/sub-канал ``login``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Tuple

from telethon.errors import (
    FloodWaitError as TelethonFloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from core.crypto import encrypt_session
from core.enums import Initiator
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.schemas.account import AccountUpdate
from core.state_machine import AccountEvent, AccountStateMachine
from worker.client_pool import ClientPool
from worker.tasks.dispatch import FloodWaitError
from worker.tasks.logging import get_logger

# worker.health импортируется ЛЕНИВО (в _governor / _around_call): worker.health
# тянет worker.tasks.logging → worker.tasks, а тот через handlers возвращается в
# login/flow — обратная дуга должна быть ленивой, иначе цикл при импорте
# worker.health раньше worker.tasks.
LOGIN_ACTION = "login"  # тип действия для governor (лимит логин-операций)

LOGIN_CHANNEL = "login"
_META_CODE_HASH = "phone_code_hash"


class LoginState(str, Enum):
    WAITING_CODE = "waiting_code"
    WAITING_PASSWORD = "waiting_password"
    SUCCESS = "success"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


# --- вспомогательные ---------------------------------------------------------


def _pool(ctx: dict) -> ClientPool:
    """Достаёт общий ClientPool из ctx воркера (создаёт лениво и переиспользует).

    ``ctx`` в arq живёт всё время процесса воркера и общий для всех задач,
    поэтому один пул обслуживает все шаги логина.
    """
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _task_queue(ctx: dict) -> TaskQueue:
    """Очередь задач из ctx (инъекция в тестах), иначе поверх ctx['redis']."""
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


def _governor(ctx: dict):
    """Governor из ctx (инъекция в тестах), иначе поверх ctx['redis']."""
    gov = ctx.get("governor")
    if gov is not None:
        return gov
    from worker.health import Governor

    return Governor(ctx.get("redis"))


async def _around_call(ctx: dict, account_id: int, call):
    """Обёртка health-монитора для login-вызовов (флудвейт не трогаем — свой разбор)."""
    from worker.health import around_telethon_call

    return await around_telethon_call(
        call,
        account_id=account_id,
        session_factory=ctx["session_factory"],
        publisher=ctx.get("publisher"),
        now=ctx.get("now"),
        handle_flood_wait=False,
    )


def _publish(
    publisher: Optional[Publisher],
    account_id: int,
    state: LoginState,
    reason: Optional[str] = None,
) -> None:
    if publisher is None:
        return
    payload: dict[str, Any] = {"account_id": account_id, "state": state.value}
    if reason is not None:
        payload["reason"] = reason
    publisher.publish(LOGIN_CHANNEL, payload)


def _read_login_data(
    session_factory: Any, account_id: int
) -> Optional[Tuple[str, Optional[str]]]:
    """Возвращает (phone, phone_code_hash|None) или None, если аккаунта нет."""
    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None:
            return None
        meta = account.meta or {}
        return account.phone, meta.get(_META_CODE_HASH)


def _store_pending(
    session_factory: Any, account_id: int, code_hash: str, session_str: str
) -> None:
    """Сохраняет phone_code_hash в meta и обновлённую сессию (шаг login_start)."""
    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        account.meta = {**(account.meta or {}), _META_CODE_HASH: code_hash}
        account.session_enc = encrypt_session(session_str.encode())
        session.commit()


def _save_session_only(session_factory: Any, account_id: int, session_str: str) -> None:
    """Сохраняет только session_enc, оставляя pending-логин (шаг 2FA-ожидания)."""
    with session_factory() as session:
        AccountRepository(session).update(
            account_id, AccountUpdate(session_enc=encrypt_session(session_str.encode()))
        )
        session.commit()


async def _finish_login(ctx: dict, account_id: int, session_str: str) -> None:
    """Успех входа: сохранить сессию, снять pending, перевести created → warming.

    Обновление session_enc/meta и переход статуса — в одной транзакции: state
    machine коммитит сессию, поэтому наши правки над тем же объектом фиксируются
    атомарно вместе с переходом.

    Сразу после перехода ставим ``warming.initial_start`` в очередь — это и есть
    запуск первичного прогрева. Enqueue идёт ЧЕРЕЗ :class:`TaskQueue` (а не прямым
    импортом функции прогрева), чтобы транспорт задач оставался единым.
    """
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        account.session_enc = encrypt_session(session_str.encode())
        account.meta = {
            k: v for k, v in (account.meta or {}).items() if k != _META_CODE_HASH
        }
        AccountStateMachine(session, publisher).transition(
            account_id, AccountEvent.WARMING_START, Initiator.AUTO
        )
    await _task_queue(ctx).enqueue(TaskName.WARMING_INITIAL_START, account_id)
    _publish(publisher, account_id, LoginState.SUCCESS)


def _code_reason(exc: Exception) -> str:
    if isinstance(exc, PhoneCodeExpiredError):
        return "код истёк"
    return "код неверный"


# --- задачи ------------------------------------------------------------------


async def login_start_impl(ctx: dict, account_id: int) -> None:
    """Запрос кода подтверждения: send_code через ClientPool, meta.phone_code_hash."""
    pool = _pool(ctx)
    publisher = ctx.get("publisher")
    session_factory = ctx["session_factory"]

    data = _read_login_data(session_factory, account_id)
    if data is None:
        _publish(publisher, account_id, LoginState.FAILED, "account not found")
        return
    phone, _ = data

    client = await pool.get(account_id)
    try:
        # governor 'login' — до реального обращения к Telegram: исчерпан → ждём.
        if not await _governor(ctx).check_and_reserve(account_id, LOGIN_ACTION):
            _publish(publisher, account_id, LoginState.RATE_LIMITED)
            return
        await client.connect()
        sent = await _around_call(
            ctx, account_id, lambda: client.send_code_request(phone)
        )
        session_str = client.session.save()
    except TelethonFloodWaitError as exc:
        # Отдаём диспетчеру — он перепланирует ретрай, это не провал.
        raise FloodWaitError(exc.seconds) from exc
    except Exception as exc:  # noqa: BLE001 - любая иная → failed
        get_logger().warning("login.start_failed", account_id=account_id, error=repr(exc))
        _publish(publisher, account_id, LoginState.FAILED, str(exc))
        return
    finally:
        await pool.release(account_id)

    _store_pending(session_factory, account_id, sent.phone_code_hash, session_str)
    _publish(publisher, account_id, LoginState.WAITING_CODE)


async def login_confirm_impl(ctx: dict, account_id: int, code: str) -> None:
    """Подтверждение кода: sign_in. Успех → warming; 2FA → waiting_password."""
    pool = _pool(ctx)
    publisher = ctx.get("publisher")
    session_factory = ctx["session_factory"]

    data = _read_login_data(session_factory, account_id)
    if data is None:
        _publish(publisher, account_id, LoginState.FAILED, "account not found")
        return
    phone, code_hash = data
    if not code_hash:
        _publish(publisher, account_id, LoginState.FAILED, "no pending login")
        return

    needs_password = False
    session_str: Optional[str] = None
    client = await pool.get(account_id)
    try:
        if not await _governor(ctx).check_and_reserve(account_id, LOGIN_ACTION):
            _publish(publisher, account_id, LoginState.RATE_LIMITED)
            return
        await client.connect()
        await _around_call(
            ctx,
            account_id,
            lambda: client.sign_in(phone=phone, code=code, phone_code_hash=code_hash),
        )
        session_str = client.session.save()
    except TelethonFloodWaitError as exc:
        raise FloodWaitError(exc.seconds) from exc
    except SessionPasswordNeededError:
        # Логин остаётся pending: сохраняем состояние сессии, ждём login_password.
        _save_session_only(session_factory, account_id, client.session.save())
        needs_password = True
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as exc:
        _publish(publisher, account_id, LoginState.FAILED, _code_reason(exc))
        return
    except Exception as exc:  # noqa: BLE001
        get_logger().warning("login.confirm_failed", account_id=account_id, error=repr(exc))
        _publish(publisher, account_id, LoginState.FAILED, str(exc))
        return
    finally:
        await pool.release(account_id)

    if needs_password:
        _publish(publisher, account_id, LoginState.WAITING_PASSWORD)
        return

    await _finish_login(ctx, account_id, session_str)


async def login_password_impl(ctx: dict, account_id: int, password: str) -> None:
    """Ввод пароля 2FA: sign_in(password=...). Успех → warming."""
    pool = _pool(ctx)
    publisher = ctx.get("publisher")
    session_factory = ctx["session_factory"]

    data = _read_login_data(session_factory, account_id)
    if data is None:
        _publish(publisher, account_id, LoginState.FAILED, "account not found")
        return
    _, code_hash = data
    if not code_hash:
        _publish(publisher, account_id, LoginState.FAILED, "no pending login")
        return

    session_str: Optional[str] = None
    client = await pool.get(account_id)
    try:
        if not await _governor(ctx).check_and_reserve(account_id, LOGIN_ACTION):
            _publish(publisher, account_id, LoginState.RATE_LIMITED)
            return
        await client.connect()
        await _around_call(ctx, account_id, lambda: client.sign_in(password=password))
        session_str = client.session.save()
    except TelethonFloodWaitError as exc:
        raise FloodWaitError(exc.seconds) from exc
    except Exception as exc:  # noqa: BLE001
        get_logger().warning("login.password_failed", account_id=account_id, error=repr(exc))
        _publish(publisher, account_id, LoginState.FAILED, str(exc))
        return
    finally:
        await pool.release(account_id)

    await _finish_login(ctx, account_id, session_str)
