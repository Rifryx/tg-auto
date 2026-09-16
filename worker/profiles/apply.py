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
            result.errors[candidate] = type(exc).__name__
            continue

    return result


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
