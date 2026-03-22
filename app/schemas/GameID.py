

from pydantic import BaseModel
from app.utils.Enums import TCG


class GameIDPublico(BaseModel):
    tcg: TCG
    id: str
