"""Проверка админ-прав.

Инварианты защиты:

1. ``user_id`` берётся ТОЛЬКО из ``require_user`` — то есть из криптографически
   подписанного Telegram initData. Клиент не может подменить: правка ломает
   HMAC-подпись, сервер вернёт 401.
2. Список админов лежит в ENV (``ADMIN_USER_IDS``), а не в БД. Даже если
   злоумышленник получил SQL-инъекцию или доступ к БД, повысить себе права
   он не сможет — не с этой стороны.
3. Не-админам отдаём 404 (Not Found), а не 403 (Forbidden). Так наличие
   админ-ручек не подтверждается наружу: обычный пользователь получит тот же
   ответ, что и на несуществующий путь.
4. Всякое админ-действие пишется в ``core.audit`` — чтобы даже при
   компрометации одного админ-аккаунта был лог.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from api.deps.auth import require_user
from core.config import get_settings


def is_admin(user_id: str) -> bool:
    return user_id in get_settings().admin_ids


async def require_admin(user_id: str = Depends(require_user)) -> str:
    """Возвращает user_id, если он в списке админов; иначе — 404."""
    if not is_admin(user_id):
        # 404 намеренно: не палим факт существования админ-эндпоинтов.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
        )
    return user_id
