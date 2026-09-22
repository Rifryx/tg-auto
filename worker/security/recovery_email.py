"""Recovery-email для 2FA (этап 7, backlog #1).

Двухшаговый flow: `edit_2fa(email=…)` в Telethon требует
``email_code_callback`` — интерактивно достать код из письма. В bulk/фоновом
режиме мы не можем блокироваться callback'ом: пользователь введёт код позже,
через API. Поэтому раскладываем Telethon-логику на две операции:

1. :func:`request_email_setup` — SRP-check текущего пароля + Update settings
   с новым email. Telegram отвечает :class:`EmailUnconfirmedError`, из которого
   мы забираем ``code_length``. Возвращаем ``EmailPending`` — сохраняем в
   ``accounts.meta.recovery_email_pending``.

2. :func:`confirm_email_code` — `account.ConfirmPasswordEmail(code)` с
   кодом, введённым пользователем. При успехе — email привязан.

Обе функции идут через :func:`around_telethon_call` — health-инциденты
(SessionRevoked/PhoneNumberBanned) автоматически попадают в state machine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from telethon import errors, password as pwd_mod
from telethon.tl import functions, types

from core.queue.publisher import Publisher
from worker.health.monitor import around_telethon_call


class RecoveryEmailError(Exception):
    """Общая ошибка recovery-email flow (кроме session/phone banned — те
    улетят в health-монитор до нашего кода)."""


class NoPasswordSetError(RecoveryEmailError):
    """У аккаунта нет 2FA — recovery email привязывать не к чему."""


class BadCurrentPasswordError(RecoveryEmailError):
    """Текущий пароль не подошёл."""


class NoPendingEmailError(RecoveryEmailError):
    """Нет ожидания подтверждения — сначала вызови request_email_setup."""


@dataclass
class EmailPending:
    """Возвращается из request_email_setup: сохраняется в БД."""

    email: str
    code_length: int


async def request_email_setup(
    client: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Optional[Publisher] = None,
    current_password: str,
    new_email: str,
) -> EmailPending:
    """Отправить код на новый recovery-email. Telegram НЕ подтверждает почту
    сразу — сначала ожидает подтверждения через ConfirmPasswordEmail.

    Возвращает ``EmailPending`` с длиной ожидаемого кода. Если у аккаунта
    нет 2FA — бросает :class:`NoPasswordSetError` (recovery email имеет
    смысл только поверх существующего пароля).
    """
    pwd = await around_telethon_call(
        lambda: client(functions.account.GetPasswordRequest()),
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
    )
    if not pwd.has_password:
        raise NoPasswordSetError("Account has no 2FA password to attach email to")

    # Соль от Telegram: перед SRP добавляем 32 случайных байта — как делает
    # сам Telethon edit_2fa (см. .venv/telethon/client/auth.py::edit_2fa).
    pwd.new_algo.salt1 += os.urandom(32)

    try:
        password_check = pwd_mod.compute_check(pwd, current_password)
    except Exception as exc:  # noqa: BLE001 — SRP ошибки скалим в понятный класс
        raise BadCurrentPasswordError(f"cannot compute SRP: {exc!r}") from exc

    new_settings = types.account.PasswordInputSettings(
        new_algo=pwd.new_algo,
        # Оставляем пароль тем же: new_password_hash=b'' в Telethon означает
        # «не менять пароль», только другие поля settings.
        new_password_hash=b"",
        hint=pwd.hint or "",
        email=new_email,
        new_secure_settings=None,
    )

    try:
        await around_telethon_call(
            lambda: client(
                functions.account.UpdatePasswordSettingsRequest(
                    password=password_check, new_settings=new_settings
                )
            ),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except errors.EmailUnconfirmedError as e:
        # Ожидаемый путь: Telegram отправил код на email.
        return EmailPending(email=new_email, code_length=int(e.code_length))
    except errors.PasswordHashInvalidError as exc:
        raise BadCurrentPasswordError("password hash rejected by Telegram") from exc

    # Если update прошёл без EmailUnconfirmedError — Telegram по каким-то
    # причинам принял email сразу (например, email уже привязан). Возвращаем
    # code_length=0 как маркер «подтверждать не нужно».
    return EmailPending(email=new_email, code_length=0)


async def confirm_email_code(
    client: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Optional[Publisher] = None,
    code: str,
) -> None:
    """Подтверждает код, присланный на recovery-email. Успех = email
    привязан к 2FA. Ошибку невалидного кода Telethon бросит как
    :class:`errors.CodeInvalidError` — API вернёт 422.
    """
    await around_telethon_call(
        lambda: client(functions.account.ConfirmPasswordEmailRequest(str(code))),
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
    )
