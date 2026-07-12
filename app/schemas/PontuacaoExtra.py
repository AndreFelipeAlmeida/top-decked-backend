from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models import PontuacaoExtraBase


class PontuacaoExtraCriarDTO(PontuacaoExtraBase):
    pass


class PontuacaoExtraPublico(PontuacaoExtraBase):
    id: int
    torneio_id: str
    criado_em: datetime
    # Dados resolvidos pra exibir a linha do histórico sem o frontend
    # precisar buscar o jogador/torneio à parte (ver PontuacaoExtraService).
    apelido: Optional[str] = None
    game_id: Optional[str] = None
    torneio_nome: Optional[str] = None
    jogo: Optional[str] = None
