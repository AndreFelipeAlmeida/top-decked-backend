from typing import Optional
from datetime import date
from pydantic import BaseModel
from app.utils.Enums import TCG


class JogadorCriadoPublico(BaseModel):
    id: int
    game_id: str
    tcg: TCG
    apelido: Optional[str] = None
    jogador_id: Optional[int] = None
    data_nascimento: Optional[date] = None
