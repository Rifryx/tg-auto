"""Bulk-действие: сгенерировать оформление из персоны и применить (этап 6 УТП).

Для каждого аккаунта:
1) читаем ``persona_id``; если не задан — item в SKIPPED (нельзя сгенерировать
   осмысленный портрет из ничего);
2) вызываем :class:`ProfileGenerator` (LLM). Результат — имя/фамилия/био/список
   username-кандидатов;
3) применяем через :func:`apply_profile_to_telegram`, синхронизируем нашу БД.

В отличие от ``apply_profile``, payload здесь ПУСТОЙ — вся индивидуализация
идёт через персону аккаунта. Это и есть УТП: каждый акк получает уникальный,
но соответствующий портрету профиль.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from core.enums import BulkActionType
from core.repositories.account import AccountRepository
from core.repositories.persona import PersonaRepository
from core.schemas.account import AccountUpdate
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from modules.profiles.generator import (
    ProfileGenerationError,
    ProfileGenerator,
    default_generator,
)
from worker.profiles.apply import apply_profile_to_telegram


class GenerateAndApplyPayload(BaseModel):
    """Опциональные подстройки. Всё остальное берётся из персоны акка."""

    model_config = ConfigDict(extra="forbid")

    llm_provider: str = "deepseek"
    apply_username: bool = True
    apply_bio: bool = True


async def _run(
    *,
    account_id: int,
    payload: GenerateAndApplyPayload,
    session_factory,
    publisher,
    client,
    generator: Optional[ProfileGenerator] = None,
    **_: object,
) -> BulkActionResult:
    # Читаем персону аккаунта в короткоживущей сессии.
    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None:
            return BulkActionResult(ok=False, skipped=True, detail={"reason": "account_missing"})
        if account.persona_id is None:
            return BulkActionResult(ok=False, skipped=True, detail={"reason": "no_persona"})
        persona = PersonaRepository(session).get(account.persona_id)
        if persona is None:
            return BulkActionResult(ok=False, skipped=True, detail={"reason": "persona_missing"})

    gen = generator or default_generator(payload.llm_provider)
    try:
        generated = await gen.generate(persona)
    except ProfileGenerationError as exc:
        return BulkActionResult(ok=False, detail={"reason": "generation_failed", "error": str(exc)})

    username_candidates = generated.username_candidates if payload.apply_username else None
    bio = generated.bio if payload.apply_bio else None

    result = await apply_profile_to_telegram(
        client,
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
        first_name=generated.first_name,
        last_name=generated.last_name or None,
        bio=bio,
        username_candidates=username_candidates,
    )

    with session_factory() as session:
        updates: dict[str, object] = {}
        if result.updated_names:
            updates["first_name"] = generated.first_name
            if generated.last_name:
                updates["last_name"] = generated.last_name
        if result.updated_bio and bio is not None:
            updates["bio"] = bio
        if result.applied_username is not None:
            updates["username"] = result.applied_username
        if updates:
            AccountRepository(session).update(account_id, AccountUpdate(**updates))
            session.commit()

    return BulkActionResult(
        ok=True,
        detail={
            "generated": generated.as_dict(),
            "applied": result.as_dict(),
        },
    )


register(
    BulkAction(
        name=BulkActionType.GENERATE_AND_APPLY_PROFILE.value,
        requires_client=True,
        payload_schema=GenerateAndApplyPayload,
        run=_run,
        title="Сгенерировать профиль из персоны и применить",
        description="LLM создаёт имя/био/username по персоне каждого аккаунта и применяет.",
    )
)
