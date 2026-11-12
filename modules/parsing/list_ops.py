"""Операции над готовыми списками (Extraction+, этап 1).

Производят новый список (``source_kind=list_op``) из существующих — без обращения
к Telegram:

* ``intersect`` — элементы, встречающиеся минимум в ``min_overlap`` списках
  (по умолчанию во всех выбранных) → «горячая» пересекающаяся аудитория;
* ``union`` — объединение с дедупом;
* ``subtract`` — из первого списка вычесть всех, кто есть в остальных;
* ``sample`` — случайная выборка ``sample_size`` из объединения.

Списки бывают ДВУХ видов, которые хранятся в разных таблицах:
* пользовательские (``parsing.list_targets``) — ключ ``tg_user_id``;
* сообщества/каналы (``parsing.community_items``) — ключ ``channel_tg_id``.
Операция определяет вид каждого источника по содержимому и работает с нужной
таблицей. Раньше поддерживались только пользовательские списки — операции над
списком каналов молча возвращали 0 (жалоба «объединение не работает вообще»).
Смешивать виды в одной операции нельзя — вернём понятную ошибку.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from modules.parsing.repositories import (
    ParsedCommunityItemRepository,
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

# Поля, которые переносим в новый список сообществ (зеркало ParsedCommunityItem).
_COMMUNITY_FIELDS = (
    "input_ref", "channel_tg_id", "access_hash", "title", "username",
    "is_public", "kind", "participants_count", "has_linked_chat",
    "linked_chat_id", "last_post_at", "is_verified", "is_scam", "is_fake",
    "slowmode_seconds", "about",
)


def _select_keys(
    op: str,
    *,
    presence: dict,
    per_list: dict[int, set],
    rep: dict,
    source_list_ids: list[int],
    min_overlap: Optional[int],
    sample_size: Optional[int],
    rng: Optional[random.Random],
) -> set:
    """Общая логика выбора ключей (одинакова для user/community)."""
    n = len(source_list_ids)
    if op == "intersect":
        # Для одного списка пересечение = сам список (порог 1). Для нескольких —
        # по умолчанию «во всех», либо min_overlap, зажатый в [1, n].
        threshold = min_overlap or n
        threshold = max(1, min(threshold, n))
        return {k for k, lids in presence.items() if len(lids) >= threshold}
    if op == "union":
        return set(rep.keys())
    if op == "subtract":
        base = set(per_list[source_list_ids[0]])
        minus: set = set()
        for lid in source_list_ids[1:]:
            minus |= per_list[lid]
        return base - minus
    # sample
    if not sample_size or sample_size < 1:
        raise ListOpError("sample requires sample_size >= 1")
    pool = list(rep.keys())
    r = rng or random.Random()
    r.shuffle(pool)
    return set(pool[:sample_size])


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
    community_repo = ParsedCommunityItemRepository(session)
    for lid in source_list_ids:
        if lists_repo.get_by_id(lid) is None:
            raise ListOpError(f"list {lid} not found")

    # Определяем вид каждого списка по содержимому: если есть строки сообществ —
    # это community-список, иначе пользовательский. Пустой список считаем
    # пользовательским (на результат не влияет). Смешивать нельзя.
    kinds: set[str] = set()
    for lid in source_list_ids:
        if community_repo.count_by_list(lid) > 0:
            kinds.add("community")
        else:
            kinds.add("user")
    if len(kinds) > 1:
        raise ListOpError(
            "нельзя смешивать списки пользователей и списки каналов/чатов "
            "в одной операции"
        )
    is_community = kinds == {"community"}

    # key -> представительная строка; presence[key] = множество списков.
    rep: dict = {}
    presence: dict = {}
    per_list: dict[int, set] = {}

    if is_community:
        for lid in source_list_ids:
            keys_here: set = set()
            for it in community_repo.list_by_list(lid):
                # Ключ дедупа: channel_tg_id, иначе input_ref (как в bulk_create).
                key = int(it.channel_tg_id) if it.channel_tg_id is not None else it.input_ref
                keys_here.add(key)
                presence.setdefault(key, set()).add(lid)
                rep.setdefault(key, {f: getattr(it, f) for f in _COMMUNITY_FIELDS})
            per_list[lid] = keys_here
    else:
        for lid in source_list_ids:
            keys_here = set()
            for t in targets_repo.list_by_list(lid):
                if t.tg_user_id is None:
                    continue
                uid = int(t.tg_user_id)
                keys_here.add(uid)
                presence.setdefault(uid, set()).add(lid)
                rep.setdefault(uid, {
                    "tg_user_id": uid,
                    "username": t.username,
                    "phone": t.phone,
                    "has_premium": t.has_premium,
                    "last_seen_bucket": t.last_seen_bucket or TargetLastSeen.UNKNOWN.value,
                })
            per_list[lid] = keys_here

    selected = _select_keys(
        op,
        presence=presence,
        per_list=per_list,
        rep=rep,
        source_list_ids=source_list_ids,
        min_overlap=min_overlap,
        sample_size=sample_size,
        rng=rng,
    )

    new_list = lists_repo.create({
        "owner_user_id": owner_user_id,
        "name": name,
        "source_kind": ParserSourceKind.LIST_OP.value,
    })
    list_id = new_list.id
    session.flush()

    rows = [rep[k] for k in selected if k in rep]
    if not rows:
        inserted = 0
    elif is_community:
        inserted = community_repo.bulk_create(list_id, rows)
    else:
        inserted = targets_repo.bulk_create(list_id, rows)

    lists_repo.update(list_id, {
        "raw_count": len(selected),
        "after_filters_count": inserted,
        "filters_breakdown": {
            "op": op,
            "sources": source_list_ids,
            "kind": "community" if is_community else "user",
        },
        "parsed_at": datetime.now(timezone.utc),
    })
    session.commit()
    return ListOpResult(list_id=list_id, inserted=inserted)
