"""Операции над готовыми списками (Extraction+, этап 1).

Производят новый список (``source_kind=list_op``) из существующих — без обращения
к Telegram:

* ``intersect`` — пользователи, встречающиеся минимум в ``min_overlap`` списках
  (по умолчанию во всех выбранных) → «горячая» пересекающаяся аудитория;
* ``union`` — объединение с дедупом;
* ``subtract`` — из первого списка вычесть всех, кто есть в остальных;
* ``sample`` — случайная выборка ``sample_size`` из объединения.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from modules.parsing.repositories import (
    ParsedListRepository,
    ParsedListTargetRepository,
)
from modules.priming.schemas.enums import ParserSourceKind, TargetLastSeen


class ListOpError(ValueError):
    """Некорректные параметры операции над списками."""


@dataclass
class ListOpResult:
    list_id: int
    inserted: int


_OPS = {"intersect", "union", "subtract", "sample"}


def run_list_op(
    session: Session,
    *,
    owner_user_id: int,
    name: str,
    op: str,
    source_list_ids: list[int],
    min_overlap: Optional[int] = None,
    sample_size: Optional[int] = None,
    rng: Optional[random.Random] = None,
) -> ListOpResult:
    if op not in _OPS:
        raise ListOpError(f"unknown op: {op!r}")
    if not source_list_ids:
        raise ListOpError("source_list_ids is empty")
    if op == "subtract" and len(source_list_ids) < 2:
        raise ListOpError("subtract requires >= 2 lists")

    lists_repo = ParsedListRepository(session)
    targets_repo = ParsedListTargetRepository(session)
    for lid in source_list_ids:
        if lists_repo.get_by_id(lid) is None:
            raise ListOpError(f"list {lid} not found")

    # tg_user_id -> представительная строка; + в скольких списках встречается.
    rep: dict[int, dict] = {}
    presence: dict[int, set[int]] = {}
    per_list: dict[int, set[int]] = {}
    for lid in source_list_ids:
        ids_here: set[int] = set()
        for t in targets_repo.list_by_list(lid):
            if t.tg_user_id is None:
                continue
            uid = int(t.tg_user_id)
            ids_here.add(uid)
            presence.setdefault(uid, set()).add(lid)
            rep.setdefault(uid, {
                "tg_user_id": uid,
                "username": t.username,
                "phone": t.phone,
                "has_premium": t.has_premium,
                "last_seen_bucket": t.last_seen_bucket or TargetLastSeen.UNKNOWN.value,
            })
        per_list[lid] = ids_here

    if op == "intersect":
        threshold = min_overlap or len(source_list_ids)
        threshold = max(2, min(threshold, len(source_list_ids)))
        selected = {uid for uid, lids in presence.items() if len(lids) >= threshold}
    elif op == "union":
        selected = set(rep.keys())
    elif op == "subtract":
        base = per_list[source_list_ids[0]]
        minus: set[int] = set()
        for lid in source_list_ids[1:]:
            minus |= per_list[lid]
        selected = base - minus
    else:  # sample
        if not sample_size or sample_size < 1:
            raise ListOpError("sample requires sample_size >= 1")
        pool = list(rep.keys())
        r = rng or random.Random()
        r.shuffle(pool)
        selected = set(pool[:sample_size])

    new_list = lists_repo.create({
        "owner_user_id": owner_user_id,
        "name": name,
        "source_kind": ParserSourceKind.LIST_OP.value,
    })
    list_id = new_list.id
    session.flush()

    rows = [rep[uid] for uid in selected if uid in rep]
    inserted = targets_repo.bulk_create(list_id, rows) if rows else 0

    lists_repo.update(list_id, {
        "raw_count": len(selected),
        "after_filters_count": inserted,
        "filters_breakdown": {"op": op, "sources": source_list_ids},
        "parsed_at": datetime.now(timezone.utc),
    })
    session.commit()
    return ListOpResult(list_id=list_id, inserted=inserted)
