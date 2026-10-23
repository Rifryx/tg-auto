"""Фоновая уборка брошенных логинов аккаунтов.

Аккаунт создаётся в статусе ``created`` сразу на шаге ввода кода (ещё до
подтверждения). Если пользователь закрыл приложение на вводе кода/2FA, фронтовая
чистка (unmount-хук мастера) не срабатывает, и в пуле зависает «пустышка» —
только номер, без информации, бесполезная.

Успешный логин переводит аккаунт в ``warming`` (а дальше в ``pool``), поэтому
любой аккаунт, оставшийся в ``created`` дольше TTL, — это брошенный недо-логин.
Cron (регистрация в ``worker/tasks/handlers.py``) периодически их удаляет;
зависимые строки снимаются каскадом (как в ``delete_account``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.enums import AccountStatus
from core.repositories.account import AccountRepository
from worker.tasks.logging import get_logger

# Сколько ждать до признания недо-логина брошенным. С запасом относительно
# времени ввода кода + 2FA (пользователь мог отвлечься на минуты).
ABANDONED_LOGIN_TTL_MIN = 60


async def sweep_abandoned_logins_impl(ctx: dict) -> dict[str, int]:
    session_factory = ctx["session_factory"]
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ABANDONED_LOGIN_TTL_MIN)
    removed = 0
    with session_factory() as session:
        repo = AccountRepository(session)
        stale = [
            a
            for a in repo.list_by_status(AccountStatus.CREATED)
            if a.created_at is not None and a.created_at < cutoff
        ]
        for account in stale:
            if repo.delete(account.id):
                session.commit()
                removed += 1
    if removed:
        get_logger().info("accounts.sweep_abandoned_logins.done", removed=removed)
    return {"removed": removed}
