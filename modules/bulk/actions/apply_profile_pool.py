"""Bulk-action apply_profile_pool (этап 6, backlog #1).

Ручной bulk-режим оформления «без LLM»: каждому аккаунту случайно выбирается
asset из пула ``profile_assets`` по kind и опциональному фильтру тегов, затем
применяется через тот же путь, что и ``apply_profile``. Аватар грузится через
``upload_avatar``.

Payload — мап kind → фильтр тегов (пустой список = «любые», отсутствие ключа =
«не менять это поле»)::

    {
      "first_name_tags": ["ru", "мужское"],
      "bio_tags": [],
      "avatar_tags": ["business"],
    }

Каждый item выбирает свои значения независимо: два аккаунта получат разные
first_name, даже если пул один и тот же.
"""

from __future__ import annotations

import random
from typing import Optional

from pydantic import BaseModel, ConfigDict

from core.enums import BulkActionType
from core.repositories.account import AccountRepository
from core.repositories.profile_asset import ProfileAssetRepository
from core.schemas.account import AccountUpdate
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.profiles.apply import apply_profile_to_telegram, upload_avatar


class ApplyProfilePoolPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None → поле не менять; [] → любой asset этого kind; [...tags] → фильтр.
    first_name_tags: Optional[list[str]] = None
    last_name_tags: Optional[list[str]] = None
    bio_tags: Optional[list[str]] = None
    avatar_tags: Optional[list[str]] = None
    # Юзернейм: если true, соберём кандидатов из шаблонов username_template
    # с подстановкой ``{n}`` на случайное число.
    username_from_pool: bool = False
    username_tags: Optional[list[str]] = None
    username_candidates_count: int = 5


def _fill_template(template: str, rng: random.Random) -> str:
    """Подстановки в шаблон. Только один плейсхолдер: ``{n}`` → 3–6 цифр."""
    if "{n}" in template:
        n = rng.randint(100, 999_999)
        return template.replace("{n}", str(n))
    return template


async def _run(
    *,
    account_id: int,
    payload: ApplyProfilePoolPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    rng = random.Random()  # свой RNG на item — независимые броски.

    first_name = last_name = bio = None
    avatar_binary = None
    username_candidates: list[str] = []
    picked_asset_ids: list[int] = []

    with session_factory() as session:
        repo = ProfileAssetRepository(session)
        if payload.first_name_tags is not None:
            asset = repo.pick_random(kind="first_name", tags_any=payload.first_name_tags or None, rng=rng)
            if asset is not None:
                first_name = asset.value
                picked_asset_ids.append(asset.id)
        if payload.last_name_tags is not None:
            asset = repo.pick_random(kind="last_name", tags_any=payload.last_name_tags or None, rng=rng)
            if asset is not None:
                last_name = asset.value
                picked_asset_ids.append(asset.id)
        if payload.bio_tags is not None:
            asset = repo.pick_random(kind="bio", tags_any=payload.bio_tags or None, rng=rng)
            if asset is not None:
                bio = asset.value
                picked_asset_ids.append(asset.id)
        if payload.avatar_tags is not None:
            asset = repo.pick_random(kind="avatar", tags_any=payload.avatar_tags or None, rng=rng)
            if asset is not None:
                avatar_binary = asset.binary
                picked_asset_ids.append(asset.id)
        if payload.username_from_pool:
            for _ in range(max(1, payload.username_candidates_count)):
                asset = repo.pick_random(
                    kind="username_template",
                    tags_any=payload.username_tags or None,
                    rng=rng,
                )
                if asset is None or asset.value is None:
                    continue
                username_candidates.append(_fill_template(asset.value, rng))
                picked_asset_ids.append(asset.id)
        session.commit()

    if all(x is None for x in (first_name, last_name, bio, avatar_binary)) and not username_candidates:
        return BulkActionResult(
            ok=False, skipped=True, detail={"reason": "empty_pool_match"}
        )

    result = await apply_profile_to_telegram(
        client,
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
        first_name=first_name,
        last_name=last_name,
        bio=bio,
        username_candidates=username_candidates or None,
    )

    avatar_result = None
    if avatar_binary is not None:
        avatar_result = await upload_avatar(
            client,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            binary=avatar_binary,
        )

    # Записываем то, что реально применилось, в accounts.
    with session_factory() as session:
        updates: dict[str, object] = {}
        if first_name is not None and result.updated_names:
            updates["first_name"] = first_name
        if last_name is not None and result.updated_names:
            updates["last_name"] = last_name
        if bio is not None and result.updated_bio:
            updates["bio"] = bio
        if result.applied_username is not None:
            updates["username"] = result.applied_username
        if updates:
            AccountRepository(session).update(account_id, AccountUpdate(**updates))
            session.commit()

    detail: dict[str, object] = {
        "assets": picked_asset_ids,
        "apply": result.as_dict(),
    }
    if avatar_result is not None:
        detail["avatar"] = avatar_result
    return BulkActionResult(ok=True, detail=detail)


register(
    BulkAction(
        name=BulkActionType.APPLY_PROFILE_POOL.value,
        requires_client=True,
        payload_schema=ApplyProfilePoolPayload,
        run=_run,
        title="Оформить из пула",
        description=(
            "Ручной bulk-режим оформления «без LLM»: каждому аккаунту "
            "случайно берётся имя/био/аватар/юзернейм из пула asset'ов."
        ),
        governor_key="bulk_profile",
    )
)
