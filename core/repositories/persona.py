from __future__ import annotations

from typing import Optional

from core.models import Persona
from core.repositories.base import BaseRepository
from core.schemas.persona import PersonaCreate, PersonaUpdate


class PersonaRepository(BaseRepository[Persona]):
    model = Persona

    def create(self, data: PersonaCreate) -> Persona:
        persona = Persona(**data.model_dump())
        return self._add(persona)

    def update(self, id_: int, data: PersonaUpdate) -> Optional[Persona]:
        persona = self.get(id_)
        if persona is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(persona, field, value)
        self.session.flush()
        return persona

    def delete(self, id_: int) -> bool:
        persona = self.get(id_)
        if persona is None:
            return False
        self.session.delete(persona)
        self.session.flush()
        return True
