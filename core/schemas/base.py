from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Базовая read-схема: читается напрямую из ORM-объекта."""

    model_config = ConfigDict(from_attributes=True)
