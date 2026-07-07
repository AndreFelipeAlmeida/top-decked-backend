from typing import Optional
from pydantic import BaseModel
from app.utils.Enums import TCG


class JogadorCriadoPublico(BaseModel):
    id: int
    game_id: str
    tcg: TCG
    apelido: Optional[str] = None
    jogador_id: Optional[int] = None
