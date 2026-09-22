"""Task-хендлеры security-операций (этап 7, backlog #1).

* ``security.request_recovery_email`` — берёт клиент, шлёт код на новый
  email, кладёт state в ``accounts.meta.recovery_email_pending``, публикует
  ``security.recovery_email_updated`` в pub/sub.
* ``security.confirm_recovery_email`` — берёт клиент, подтверждает код,
  чистит pending и публикует событие.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from core.crypto import CryptoError, decrypt_password
from core.queue.publisher import Publisher
from core.repositories.account import AccountRepository
from worker.security.recovery_email import (
    BadCurrentPasswordError,
    NoPasswordSetError,
    RecoveryEmailError,
    confirm_email_code,
    request_email_setup,
)
from worker.tasks.logging import get_logger

RECOVERY_EMAIL_CHANNEL = "security.recovery_email_updated"


def _publish(publisher: Optional[Publisher], account_id: int, payload: dict) -> None:
    if publisher is None:
        return
    publisher.publish(RECOVERY_EMAIL_CHANNEL, {"account_id": account_id, **payload})


def _set_pending(
    session_factory,
    account_id: int,
    email: str,
    code_length: int,
    now: datetime,
) -> None:
    """Записать email в meta.recovery_email_pending. accounts.meta — JSONB,
    сохраняет копию dict'а, чтобы не менять in-place и триггернуть update."""
    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None:
            return
        meta = dict(account.meta or {})
        meta["recovery_email_pending"] = {
            "email": email,
            "code_length": code_length,
            "requested_at": now.isoformat(),
        }
        account.meta = meta
        session.commit()


def _clear_pending_and_set(
    session_factory, account_id: int, email: str, now: datetime
) -> None:
    """После confirm: pending → recovery_email, чистим временное поле."""
    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None:
            return
        meta = dict(account.meta or {})
        meta.pop("recovery_email_pending", None)
        meta["recovery_email"] = email
        meta["recovery_email_confirmed_at"] = now.isoformat()
        account.meta = meta
        session.commit()


async def request_recovery_email_impl(
    ctx: dict, account_id: int, email: str, current_password_enc_b64: str
) -> dict[str, Any]:
    """Инициирует привязку recovery-email к 2FA (шаг 1/2)."""
    now = ctx.get("now") or datetime.now(timezone.utc)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    client_pool = ctx["client_pool"]

    import base64
    try:
        password_enc = base64.b64decode(current_password_enc_b64)
        current_password = decrypt_password(password_enc).decode("utf-8")
    except (CryptoError, ValueError) as exc:
        _publish(publisher, account_id, {"state": "failed", "reason": "bad_password_enc"})
        return {"ok": False, "reason": "bad_password_enc", "error": repr(exc)}

    client = await client_pool.get(account_id)
    try:
        pending = await request_email_setup(
            client,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            current_password=current_password,
            new_email=email,
        )
    except NoPasswordSetError:
        _publish(publisher, account_id, {"state": "failed", "reason": "no_2fa"})
        return {"ok": False, "reason": "no_2fa"}
    except BadCurrentPasswordError as exc:
        _publish(publisher, account_id, {"state": "failed", "reason": "bad_password"})
        return {"ok": False, "reason": "bad_password", "error": repr(exc)}
    except RecoveryEmailError as exc:
        _publish(publisher, account_id, {"state": "failed", "reason": "recovery_email_error"})
        return {"ok": False, "reason": "recovery_email_error", "error": repr(exc)}
    finally:
        await client_pool.release(account_id)

    _set_pending(session_factory, account_id, pending.email, pending.code_length, now)

    if pending.code_length == 0:
        # Редкий путь: Telegram принял email без подтверждения. Сразу
        # переводим в confirmed-состояние.
        _clear_pending_and_set(session_factory, account_id, pending.email, now)
        _publish(
            publisher,
            account_id,
            {"state": "confirmed", "email": pending.email, "auto": True},
        )
        get_logger().info(
            "security.request_recovery_email.auto_confirmed",
            account_id=account_id, email=pending.email,
        )
        return {"ok": True, "state": "confirmed", "code_length": 0}

    _publish(
        publisher,
        account_id,
        {"state": "pending", "email": pending.email, "code_length": pending.code_length},
    )
    get_logger().info(
        "security.request_recovery_email.pending",
        account_id=account_id, email=pending.email, code_length=pending.code_length,
    )
    return {"ok": True, "state": "pending", "code_length": pending.code_length}


async def confirm_recovery_email_impl(
    ctx: dict, account_id: int, code: str
) -> dict[str, Any]:
    """Подтверждает код, введённый пользователем (шаг 2/2)."""
    now = ctx.get("now") or datetime.now(timezone.utc)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    client_pool = ctx["client_pool"]

    # Читаем pending email из meta.
    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None:
            _publish(publisher, account_id, {"state": "failed", "reason": "no_account"})
            return {"ok": False, "reason": "no_account"}
        pending = (account.meta or {}).get("recovery_email_pending")
    if pending is None:
        _publish(publisher, account_id, {"state": "failed", "reason": "no_pending"})
        return {"ok": False, "reason": "no_pending"}

    client = await client_pool.get(account_id)
    try:
        await confirm_email_code(
            client,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            code=code,
        )
    except Exception as exc:  # noqa: BLE001 - CodeInvalid, etc.
        _publish(
            publisher, account_id,
            {"state": "failed", "reason": "code_invalid", "error": repr(exc)},
        )
        get_logger().warning(
            "security.confirm_recovery_email.failed",
            account_id=account_id, error=repr(exc),
        )
        return {"ok": False, "reason": "code_invalid", "error": repr(exc)}
    finally:
        await client_pool.release(account_id)

    _clear_pending_and_set(session_factory, account_id, pending["email"], now)
    _publish(publisher, account_id, {"state": "confirmed", "email": pending["email"]})
    get_logger().info(
        "security.confirm_recovery_email.done",
        account_id=account_id, email=pending["email"],
    )
    return {"ok": True, "state": "confirmed", "email": pending["email"]}
