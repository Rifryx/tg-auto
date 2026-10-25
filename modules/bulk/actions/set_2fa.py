"""Bulk-действие: установить/сменить/снять двухфакторный пароль (этап 7 УТП).

Ключевые соображения безопасности:
* В ``bulk_jobs.payload`` НИКОГДА не летит plaintext-пароль. API-эндпоинт-обёртка
  (``POST /accounts/bulk/set-2fa``) шифрует password через ``crypto.encrypt_password``
  и кладёт в payload base64-строку ``password_enc_b64``.
* Action на воркере расшифровывает payload через ``crypto.decrypt_password``,
  использует пароль ТОЛЬКО в вызове ``client.edit_2fa`` и не пишет наружу.
* После успеха ``accounts.two_factor_password_enc`` обновляется тем же
  шифрованным blob'ом — источник правды для будущих логинов.
* ``account_health.has_2fa`` синхронизируется тут же (для Health Score).

Режимы:
* ``set_or_change``: если у аккаунта уже есть 2FA — используем сохранённый
  пароль как ``current_password`` и меняем. Если нет — устанавливаем новый.
* ``remove``: снять пароль; нужен ``password_enc_b64`` только для current
  (в mode=remove это тот же старый пароль). ``new_password=None`` при вызове
  edit_2fa.
"""

from __future__ import annotations

import base64
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.crypto import CryptoError, decrypt_password, encrypt_password
from core.enums import BulkActionType, PhoneStatus
from core.repositories.account import AccountRepository
from core.repositories.account_health import AccountHealthRepository
from core.schemas.account_health import AccountHealthUpdate
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register


class Set2FAPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["set_or_change", "remove"] = "set_or_change"
    # Base64(Fernet(password)) — НОВЫЙ пароль (для set_or_change).
    password_enc_b64: Optional[str] = None
    # Base64(Fernet(password)) — ТЕКУЩИЙ пароль. Если задан, перебивает
    # сохранённый в accounts.two_factor_password_enc. Нужен, когда:
    # 1) У аккаунта реально есть 2FA, но мы его не сохранили (импорт сессии
    #    без ввода пароля).
    # 2) Сохранённый пароль неактуален (юзер менял его вручную через Telegram
    #    и наш автоматический edit_2fa падает с PasswordHashInvalid).
    # Без этого remove/change на таких аккаунтах не работает в принципе —
    # Telegram требует current_password на изменение/снятие.
    current_password_enc_b64: Optional[str] = None
    hint: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=254)


async def _run(
    *,
    account_id: int,
    payload: Set2FAPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    # 1) Читаем текущий шифрованный пароль (если есть) + has_2fa из health.
    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None:
            return BulkActionResult(ok=False, skipped=True, detail={"reason": "account_missing"})
        current_enc = account.two_factor_password_enc
        health = AccountHealthRepository(session).get(account_id)
        has_2fa_health = bool(getattr(health, "has_2fa", False)) if health else False

    # 2) Декодируем новый payload (если задан).
    new_password: Optional[str] = None
    new_enc: Optional[bytes] = None
    if payload.password_enc_b64:
        try:
            new_enc = base64.b64decode(payload.password_enc_b64)
            new_password = decrypt_password(new_enc).decode("utf-8")
        except (CryptoError, ValueError) as exc:
            return BulkActionResult(
                ok=False,
                detail={"reason": "invalid_password_enc", "error": repr(exc)},
            )

    # 2.5) Приоритет: current_password_enc_b64 из payload > stored. Если
    # пользователь явно ввёл текущий пароль в UI, доверяем ему — сохранённый
    # мог устареть (сменили вручную через Telegram) или быть пустым (импорт).
    current_password: Optional[str] = None
    if payload.current_password_enc_b64:
        try:
            override_enc = base64.b64decode(payload.current_password_enc_b64)
            current_password = decrypt_password(override_enc).decode("utf-8")
        except (CryptoError, ValueError) as exc:
            return BulkActionResult(
                ok=False,
                detail={"reason": "invalid_current_password_enc", "error": repr(exc)},
            )
    elif current_enc is not None:
        try:
            current_password = decrypt_password(current_enc).decode("utf-8")
        except CryptoError as exc:
            return BulkActionResult(
                ok=False,
                detail={"reason": "cannot_decrypt_current", "error": repr(exc)},
            )

    # 3) Готовим аргументы edit_2fa под режим.
    if payload.mode == "remove":
        if current_password is None:
            # Различаем два случая по health.has_2fa:
            # - реально нет 2FA (health.has_2fa=False/None) → скипаем (нечего
            #   снимать, идемпотентность), как было до фикса current_password;
            # - 2FA есть, но пароля ни ввели, ни сохранили → явная ошибка,
            #   чтобы UI подсказал ввести вручную.
            if not has_2fa_health:
                return BulkActionResult(
                    ok=False, skipped=True, detail={"reason": "no_2fa"}
                )
            return BulkActionResult(
                ok=False, detail={"reason": "need_current_password"}
            )
        edit_kwargs = {"current_password": current_password, "new_password": None}
    else:  # set_or_change
        if new_password is None:
            return BulkActionResult(
                ok=False, detail={"reason": "new_password_required"}
            )
        edit_kwargs = {
            "current_password": current_password,
            "new_password": new_password,
            "hint": payload.hint or "",
        }
        if payload.email:
            edit_kwargs["email"] = payload.email

    # 4) Реальный вызов Telethon. edit_2fa — высокоуровневый helper, сам
    # обменивается challenge'ом (SRP). Ловим любые исключения → item failed.
    try:
        await client.edit_2fa(**edit_kwargs)
    except Exception as exc:  # noqa: BLE001
        return BulkActionResult(
            ok=False, detail={"reason": "edit_2fa_failed", "error": repr(exc)}
        )

    # 5) Синхронизируем БД: наш аккаунт + health_snapshot.has_2fa.
    with session_factory() as session:
        acc_repo = AccountRepository(session)
        account = acc_repo.get(account_id)
        if account is None:
            return BulkActionResult(ok=False, skipped=True, detail={"reason": "account_gone"})
        if payload.mode == "remove":
            account.two_factor_password_enc = None
            account.two_factor_hint = None
        else:
            # Пере-шифровываем свежим Fernet-токеном, а не переиспользуем blob
            # из payload (payload мог быть создан под другим ключом ротации).
            account.two_factor_password_enc = encrypt_password(new_password.encode())
            account.two_factor_hint = payload.hint or None
        AccountHealthRepository(session).update(
            account_id,
            AccountHealthUpdate(has_2fa=(payload.mode != "remove")),
        )
        session.commit()

    return BulkActionResult(
        ok=True,
        detail={
            "mode": payload.mode,
            "hint_set": bool(payload.hint) if payload.mode != "remove" else False,
            "has_2fa_after": payload.mode != "remove",
        },
    )


register(
    BulkAction(
        name=BulkActionType.SET_2FA.value,
        requires_client=True,
        payload_schema=Set2FAPayload,
        run=_run,
        title="Управление 2FA",
        description="Установить/сменить/снять двухфакторный пароль на выборке.",
        governor_key="bulk_security",
    )
)
