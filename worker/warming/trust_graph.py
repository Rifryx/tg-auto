"""Trust-graph: поиск аккаунтов-«соседей» одного аккаунта (этап 10, backlog #2).

«Сосед» = другой аккаунт того же владельца, естественно связанный с исходным:
* тот же проект (``accounts.project_id``);
* та же персона (``accounts.persona_id``);
* та же commenting-кампания (``commenting.campaign_accounts``).

Peer должен иметь публичный ``username`` (без него мы не можем к нему
обратиться через ``client.get_entity`` без обмена контактами) и не быть в
терминальном состоянии (``banned``/``retired``).

Действие ``interact_with_peer`` использует :func:`find_trust_peer_username`
для получения одного случайного peer'а на каждый tick. При большом парке
запрос отработает быстро благодаря индексам ``ix_accounts_project_id`` и
``ix_accounts_persona_id``.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.enums import AccountStatus
from core.models import Account


_TERMINAL_STATUSES = (
    AccountStatus.BANNED.value,
    AccountStatus.RETIRED.value,
)


def find_trust_peer_username(
    session: Session,
    account_id: int,
    *,
    project_id: Optional[int],
    persona_id: Optional[int],
    campaign_ids: Optional[list[int]] = None,
    rng: Any = None,
) -> Optional[str]:
    """Найти публичный username peer'а. Возвращает None, если некому.

    * Peer выбирается случайно через ``ORDER BY random() LIMIT 1``. При
      небольшом парке (десятки/сотни аккаунтов) это O(N) sort — приемлемо;
      для десятков тысяч имеет смысл keyset+random offset (по триггеру).
    * ``campaign_ids`` передаём заранее собранным списком (одним SELECT
      снаружи), чтобы не тащить схему ``commenting.*`` в этот helper.
      None или [] — не искать по кампании.
    """
    if project_id is None and persona_id is None and not campaign_ids:
        return None

    stmt = select(Account.username).where(
        Account.id != account_id,
        Account.username.is_not(None),
        Account.username != "",
        Account.status.notin_(_TERMINAL_STATUSES),
    )

    conditions = []
    if project_id is not None:
        conditions.append(Account.project_id == project_id)
    if persona_id is not None:
        conditions.append(Account.persona_id == persona_id)
    if campaign_ids:
        # id peer'а должен присутствовать в campaign_accounts с одной из
        # ``campaign_ids``. Импорт лениво — trust_graph общий helper, а
        # commenting модуль его использует; ленивый импорт исключает цикл.
        from modules.commenting.models import CampaignAccount

        conditions.append(
            Account.id.in_(
                select(CampaignAccount.account_id).where(
                    CampaignAccount.campaign_id.in_(campaign_ids)
                )
            )
        )
    stmt = stmt.where(or_(*conditions))
    stmt = stmt.order_by(func.random()).limit(1)
    result = session.execute(stmt).scalar_one_or_none()
    return result


def collect_campaign_ids(session: Session, account_id: int) -> list[int]:
    """Список commenting-кампаний, в которых состоит аккаунт (обычно 0-1).

    Отдельная функция, чтобы helper выше был чистым и удобно мокался.
    """
    from modules.commenting.models import CampaignAccount

    stmt = select(CampaignAccount.campaign_id).where(
        CampaignAccount.account_id == account_id
    )
    return [row for row in session.execute(stmt).scalars().all()]
