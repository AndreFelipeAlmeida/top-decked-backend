from typing import Optional
from pydantic import BaseModel, Field
from app.models import JogadorTorneioLinkBase
from app.schemas.Composicao import ComposicaoUnidadePublico, RepresentacaoComposicaoPublico


class JogadorTorneioLinkPublico(JogadorTorneioLinkBase):
    jogador_id: Optional[int]
    game_id: Optional[str]
    composicao_representacao: Optional[RepresentacaoComposicaoPublico] = None
    composicao_unidades: list[ComposicaoUnidadePublico] = Field(default_factory=list)
    # Calculada na hora (Temporada vigente + data de nascimento do
    # JogadorCriado) — nunca armazenada. Ver docs/TEMPORADAS.md.
    categoria: Optional[str] = None


class PontuacaoManualDTO(BaseModel):
    pontuacao: float
    pontuacao_com_regras: float


class RegraJogadorDTO(BaseModel):
    # None = sem regra extra — o jogador usa só a regra básica do torneio,
    # sem nenhum ajuste. Ver JogadorTorneioLinkBase.regra_extra_id.
    regra_extra_id: Optional[int] = None


class AdicionarJuizDTO(BaseModel):
    jogador_criado_id: int
