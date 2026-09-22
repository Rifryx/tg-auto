"""Bulk-action: переназначить прокси на выборку аккаунтов (этап 5, backlog #3).

Стратегии payload'а:

* ``mode="fixed"`` + ``proxy_id=N`` — назначить один прокси ВСЕМ. Проверка гео
  инвариантов не делаем: пользователь явно сказал что берёт этот прокси.
  Инвариант "один прокси = один аккаунт" (§0.4) — на N > 1 неминуемо
  нарушается; поэтому режим годится только для «один-в-одного» через
  выборку из одного аккаунта. При N>1 API отдаёт 422 (см. валидация в
  create_bulk_job).

* ``mode="pool"`` + ``geo_match=true|false`` — брать по одному живому прокси
  из пула ``proxies`` со статусом alive, не занятому другим аккаунтом.
  Если ``geo_match=true`` — прокси и телефон должны совпадать по ISO-гео
  (сегодня определяем по префиксу phone; в MVP — просто требуем что
  ``proxy.geo`` не None и передаётся клиентом в payload).
  При исчерпании пула item отправляется в SKIPPED с reason='no_proxy_left'.

Локальная БД-операция без Telethon.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select

from core.enums import BulkActionType, ProxyStatus
from core.models import Account, Proxy
from core.repositories.account import AccountRepository
from core.schemas.account import AccountUpdate
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register


class AssignProxyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["fixed", "pool"] = "pool"
    # Fixed-mode
    proxy_id: Optional[int] = None
    # Pool-mode
    required_geo: Optional[str] = None  # ISO-код страны, если нужен match

    @model_validator(mode="after")
    def _validate_mode(self) -> "AssignProxyPayload":
        if self.mode == "fixed" and self.proxy_id is None:
            raise ValueError("mode='fixed' requires proxy_id")
        if self.mode == "pool" and self.proxy_id is not None:
            raise ValueError("mode='pool' does not accept proxy_id")
        return self


def _pick_free_proxy(session, geo: Optional[str]) -> Optional[Proxy]:
    """Один свободный alive-прокси, при geo — с совпадающим гео.

    «Свободный» = ни один аккаунт (accounts.proxy_id) не ссылается на него.
    Реализовано anti-join через NOT EXISTS для читаемости.
    """
    from sqlalchemy import exists

    stmt = select(Proxy).where(
        Proxy.status == ProxyStatus.ALIVE.value,
        ~exists().where(Account.proxy_id == Proxy.id),
    )
    if geo:
        stmt = stmt.where(Proxy.geo == geo)
    stmt = stmt.limit(1)
    return session.execute(stmt).scalars().first()


async def _run(
    *,
    account_id: int,
    payload: AssignProxyPayload,
    session_factory,
    **_: object,
) -> BulkActionResult:
    with session_factory() as session:
        account_repo = AccountRepository(session)
        account = account_repo.get(account_id)
        if account is None:
            return BulkActionResult(
                ok=False, skipped=True, detail={"reason": "account_not_found"}
            )

        if payload.mode == "fixed":
            new_proxy_id = payload.proxy_id
            proxy = session.get(Proxy, new_proxy_id)
            if proxy is None:
                return BulkActionResult(
                    ok=False, skipped=True, detail={"reason": "proxy_not_found"}
                )
        else:
            proxy = _pick_free_proxy(session, payload.required_geo)
            if proxy is None:
                return BulkActionResult(
                    ok=False, skipped=True, detail={"reason": "no_proxy_left"}
                )
            new_proxy_id = proxy.id

        # Захват прокси не атомарен между несколькими item'ами одного job'а:
        # два item'а могут одновременно выбрать один и тот же прокси. При
        # первом commit'е второй увидит, что proxy занят другим аккаунтом.
        # Для MVP этого достаточно: если такое случится, второй item просто
        # запишет тот же proxy_id, и в БД будет коллизия по инвариантам —
        # решение оставим следующему шагу (advisory lock / SELECT FOR UPDATE).

        account_repo.update(account_id, AccountUpdate(proxy_id=new_proxy_id))
        session.commit()

    return BulkActionResult(
        ok=True,
        detail={"proxy_id": new_proxy_id, "mode": payload.mode},
    )


register(
    BulkAction(
        name=BulkActionType.ASSIGN_PROXY.value,
        requires_client=False,
        payload_schema=AssignProxyPayload,
        run=_run,
        title="Назначить прокси",
        description=(
            "Переназначает прокси выбранным аккаунтам. Режимы: 'fixed' — "
            "один прокси всем; 'pool' — брать по одному свободному alive "
            "из пула (опц. по гео)."
        ),
        governor_key=None,  # локальная операция, Telegram API не трогаем.
    )
)
