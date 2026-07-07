from typing import Optional
from pydantic import BaseModel, Field
from app.models import JogadorTorneioLinkBase
from app.schemas.Composicao import ComposicaoUnidadePublico, RepresentacaoComposicaoPublico


class JogadorTorneioLinkPublico(JogadorTorneioLinkBase):
    jogador_id: Optional[int]
    game_id: Optional[str]
    composicao_representacao: Optional[RepresentacaoComposicaoPublico] = None
    composicao_unidades: list[ComposicaoUnidadePublico] = Field(default_factory=list)


class PontuacaoManualDTO(BaseModel):
    pontuacao: float
    pontuacao_com_regras: float


class RegraJogadorDTO(BaseModel):
    # None = volta a usar a regra básica do torneio para este jogador.
    tipo_jogador_id: Optional[int] = None
