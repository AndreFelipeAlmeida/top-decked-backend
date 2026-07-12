from datetime import date
from typing import Optional
from pydantic import BaseModel
from app.models import EventoBase, MetaEventoBase, RegraPontuacaoEventoBase, RegraPontuacaoManualEventoBase
from app.schemas.Loja import LojaPublico


class EventoCriarDTO(EventoBase):
    pass


class EventoCriarOrganizadorDTO(EventoBase):
    loja_id: int


class EventoAtualizarDTO(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    data_inicio: Optional[date] = None
    data_fim: Optional[date] = None


class MetaEventoCriarDTO(MetaEventoBase):
    pass


class MetaEventoPublico(MetaEventoBase):
    id: int
    evento_id: int


class RegraPontuacaoEventoCriarDTO(RegraPontuacaoEventoBase):
    pass


class RegraPontuacaoEventoPublico(RegraPontuacaoEventoBase):
    id: int
    evento_id: int


class RegraPontuacaoManualEventoCriarDTO(RegraPontuacaoManualEventoBase):
    pass


class RegraPontuacaoManualEventoPublico(RegraPontuacaoManualEventoBase):
    id: int
    evento_id: int


class ParticipanteEventoAdicionarDTO(BaseModel):
    jogador_criado_id: int


class ComposicaoPontoPublico(BaseModel):
    motivo: str
    pontos: float


class ParticipanteEventoPublico(BaseModel):
    id: int
    jogador_criado_id: int
    apelido: Optional[str] = None
    game_id: Optional[str] = None
    foto: Optional[str] = None
    pontos_automaticos: float
    pontos_manuais: float
    pontos_total: float
    composicao_pontos: list[ComposicaoPontoPublico] = []


class PontosManualEventoCriarDTO(BaseModel):
    jogador_criado_id: int
    descricao: str
    pontos: float


class EventoPublico(EventoBase):
    id: int
    loja_id: int
    loja: Optional[LojaPublico] = None
    # AGENDADO (ainda não começou) / ATIVO (dentro do período) / ENCERRADO —
    # calculado na hora a partir de data_inicio/data_fim, nunca armazenado.
    status: str


class EventoCompletoPublico(EventoPublico):
    metas: list[MetaEventoPublico]
    regras: list[RegraPontuacaoEventoPublico]
    regras_manuais: list[RegraPontuacaoManualEventoPublico]
    participantes: list[ParticipanteEventoPublico]
