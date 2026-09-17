"""Роуты персон: CRUD (PROJECT-STAGES §6/§10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.limits import enforce_limit
from core.repositories.persona import PersonaRepository
from core.schemas.persona import PersonaCreate, PersonaRead, PersonaUpdate

router = APIRouter(
    prefix="/personas", tags=["personas"], dependencies=[Depends(require_user)]
)


@router.get("", response_model=list[PersonaRead])
def list_personas(session: Session = Depends(get_session)) -> list[PersonaRead]:
    personas = PersonaRepository(session).list_all()
    return [PersonaRead.model_validate(p) for p in personas]


@router.get("/{persona_id}", response_model=PersonaRead)
def get_persona(persona_id: int, session: Session = Depends(get_session)) -> PersonaRead:
    persona = PersonaRepository(session).get(persona_id)
    if persona is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"persona {persona_id} not found")
    return PersonaRead.model_validate(persona)


@router.post("", response_model=PersonaRead, status_code=status.HTTP_201_CREATED)
def create_persona(
    body: PersonaCreate,
    session: Session = Depends(get_session),
    _limit: None = Depends(enforce_limit("personas_max")),
) -> PersonaRead:
    persona = PersonaRepository(session).create(body)
    session.commit()
    return PersonaRead.model_validate(persona)


@router.patch("/{persona_id}", response_model=PersonaRead)
def patch_persona(
    persona_id: int, body: PersonaUpdate, session: Session = Depends(get_session)
) -> PersonaRead:
    persona = PersonaRepository(session).update(persona_id, body)
    if persona is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"persona {persona_id} not found")
    session.commit()
    return PersonaRead.model_validate(persona)


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_persona(persona_id: int, session: Session = Depends(get_session)) -> None:
    if not PersonaRepository(session).delete(persona_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"persona {persona_id} not found")
    session.commit()
