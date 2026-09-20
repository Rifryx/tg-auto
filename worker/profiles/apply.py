"""Применение оформления профиля через Telethon (этап 6 УТП).

Публичный API:
* :func:`apply_profile_to_telegram` — обновляет first/last name + bio через
  ``UpdateProfileRequest``, и, если задан username, пытается его установить
  через ``UpdateUsernameRequest`` (при коллизии — перебор кандидатов).
* :func:`check_username_free` — проба доступности одного username через
  ``CheckUsernameRequest``.

Обе процедуры проходят через :func:`around_telethon_call`, поэтому:
* health-инциденты (FloodWait / spam_block / session_revoked) автоматически
  попадают в ``health_events`` и в state machine;
* username-специфичные ошибки (``UsernameOccupiedError`` / ``UsernameInvalidError``)
  трактуются как ожидаемые «не подошёл» и НЕ считаются health-инцидентом.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import io

import httpx
from telethon.errors import (
    UsernameInvalidError,
    UsernameNotModifiedError,
    UsernameOccupiedError,
)
from telethon.tl.functions.account import (
    CheckUsernameRequest,
    UpdateProfileRequest,
    UpdateUsernameRequest,
)
from telethon.tl.functions.photos import UploadProfilePhotoRequest

from core.queue.publisher import Publisher
from worker.health.monitor import around_telethon_call


@dataclass
class ProfileApplyResult:
    """Что удалось применить, что нет."""

    updated_names: bool = False
    updated_bio: bool = False
    applied_username: Optional[str] = None
    tried_usernames: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "updated_names": self.updated_names,
            "updated_bio": self.updated_bio,
            "applied_username": self.applied_username,
            "tried_usernames": list(self.tried_usernames),
            "errors": dict(self.errors),
        }


async def apply_profile_to_telegram(
    client: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Optional[Publisher] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    bio: Optional[str] = None,
    username_candidates: Optional[list[str]] = None,
) -> ProfileApplyResult:
    """Применяет переданные части профиля; берёт первый свободный username."""
    result = ProfileApplyResult()

    if any(v is not None for v in (first_name, last_name, bio)):
        # UpdateProfileRequest принимает None → «не менять».
        await around_telethon_call(
            lambda: client(
                UpdateProfileRequest(
                    first_name=first_name,
                    last_name=last_name,
                    about=bio,
                )
            ),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
        result.updated_names = first_name is not None or last_name is not None
        result.updated_bio = bio is not None

    for candidate in username_candidates or []:
        result.tried_usernames.append(candidate)
        # Backlog #этап6.3: проактивная проверка через CheckUsername до
        # UpdateUsername. Так мы избегаем лишнего UpdateUsernameRequest на
        # заведомо занятые/невалидные (антифрод не любит частые правки).
        try:
            free = await around_telethon_call(
                lambda c=candidate: client(CheckUsernameRequest(username=c)),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
        except (UsernameInvalidError, UsernameOccupiedError) as exc:
            result.errors[candidate] = type(exc).__name__
            continue
        if not free:
            result.errors[candidate] = "occupied"
            continue

        try:
            await around_telethon_call(
                lambda c=candidate: client(UpdateUsernameRequest(username=c)),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            result.applied_username = candidate
            break
        except UsernameNotModifiedError:
            result.applied_username = candidate  # уже стоял этот username
            break
        except (UsernameOccupiedError, UsernameInvalidError) as exc:
            # Гонка: между CheckUsername и UpdateUsername кто-то занял.
            # Просто пробуем следующего кандидата.
            result.errors[candidate] = type(exc).__name__
            continue

    return result


async def upload_avatar(
    client: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Optional[Publisher] = None,
    binary: Optional[bytes] = None,
    url: Optional[str] = None,
    filename: str = "avatar.jpg",
    http_timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Ставит аватар аккаунту (этап 6, backlog #2).

    Источник — либо готовые байты (``binary``), либо URL (``url``). При URL
    скачивание идёт по-простому через ``httpx`` без прокси аккаунта: сеть
    сервера. Это осознанный компромисс MVP — risk раскрытия IP серверной
    приемлем в single-tenant deploy; когда потребуется — переезжаем на
    aiohttp через per-account proxy.

    Возвращает ``{ok: bool, mime: str|None, error?: str}``.
    """
    if binary is None and not url:
        return {"ok": False, "error": "no_source"}

    blob: Optional[bytes] = binary
    if blob is None and url:
        try:
            async with httpx.AsyncClient(timeout=http_timeout_seconds) as http:
                resp = await http.get(url)
                resp.raise_for_status()
                blob = resp.content
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"download_failed: {exc}"}

    if not blob:
        return {"ok": False, "error": "empty_blob"}

    # Telethon.upload_file принимает file-like/bytes. Ставим свой filename,
    # чтобы Telegram корректно определил как photo.
    file_obj = io.BytesIO(blob)
    file_obj.name = filename

    try:
        input_file = await around_telethon_call(
            lambda: client.upload_file(file_obj, file_name=filename),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
        await around_telethon_call(
            lambda: client(UploadProfilePhotoRequest(file=input_file)),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"upload_failed: {exc!r}"}

    return {"ok": True}


async def check_username_free(
    client: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Optional[Publisher] = None,
    username: str,
) -> bool:
    try:
        free = await around_telethon_call(
            lambda: client(CheckUsernameRequest(username=username)),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except (UsernameInvalidError, UsernameOccupiedError):
        return False
    return bool(free)
