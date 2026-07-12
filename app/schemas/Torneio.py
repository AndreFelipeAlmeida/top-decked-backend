from typing import Optional, List, Dict
from app.schemas.JogadorTorneioLink import JogadorTorneioLinkPublico
from app.schemas.Loja import LojaPublico
from app.schemas.Rodada import RodadaPublico
from app.models import TorneioBase, StatusTorneio
from datetime import date, time, datetime
from app.utils.Enums import TCG, FormatoMD, FormatoTorneio, TipoTorneio
from pydantic import BaseModel, field_validator

class TorneioAtualizar(TorneioBase):
    nome: str | None = None
    descricao: str | None = None
    cidade: str | None = None
    estado: str | None = None
    tempo_por_rodada: int | None = None
    data_planejada: date | None = None
    vagas: int | None = None
    hora_planejada: time | None = None
    formato: FormatoTorneio | None = None
    melhor_de: FormatoMD | None = None
    tipo: str | None = None
    taxa: float | None = None
    premio: str | None = None
    n_rodadas: int | None = None
    pontuacao_de_participacao: int | None = None
    regra_basica_id: int | None = None
    regras_adicionais: Optional[Dict[str, int]] | None = None
    inicio_real: datetime | None = None
    fim_real: datetime | None = None
    conta_em_eventos: bool | None = None

    # Campos de data/hora vêm de <input type="date/time/datetime-local">, que
    # mandam string vazia (não null) quando o usuário limpa o campo — e o
    # Pydantic rejeita "" como data/hora inválida em vez de tratar como "sem
    # valor". `formato` tem o mesmo problema: o <Select> do formulário de
    # edição usa `torneio?.formato ?? ''` como valor inicial
    # (TournamentEditDetails.tsx) — um torneio sem formato definido (comum em
    # importados) faz o form submeter `""`, que o enum rejeita com 422 em vez
    # de tratar como "sem valor". Normaliza pra None antes da validação de
    # tipo. `melhor_de` NÃO entra aqui de propósito: é NOT NULL no banco (tem
    # default MD1), e diferente de `formato` esse fallback pra `''` no form
    # nunca é de fato alcançável (o form só renderiza depois do torneio
    # carregar, e `melhor_de` sempre vem preenchido) — normalizar `''` pra
    # `None` aqui violaria a constraint NOT NULL se algum dia isso mudasse.
    @field_validator("data_planejada", "hora_planejada", "inicio_real", "fim_real", "formato", mode="before")
    @classmethod
    def vazio_vira_none(cls, valor):
        if valor == "":
            return None
        return valor


class CriarTorneioOrganizadorDTO(BaseModel):
    loja_id: int
    nome: Optional[str] = None
    descricao: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    tempo_por_rodada: int = 30
    data_planejada: date
    vagas: int = 0
    hora_planejada: Optional[time] = None
    formato: Optional[FormatoTorneio] = None
    melhor_de: FormatoMD = FormatoMD.MD1
    jogo: TCG = TCG.POKEMON
    tipo: TipoTorneio = TipoTorneio.CRIADO
    taxa: float = 0
    premio: Optional[str] = None
    n_rodadas: int = 0
    regra_basica_id: Optional[int] = None
    pontuacao_de_participacao: int = 0
    conta_em_eventos: bool = True


class TorneioPublico(TorneioBase):
    id: str
    status: StatusTorneio
    jogadores: List["JogadorTorneioLinkPublico"] | None
    rodadas: List["RodadaPublico"] | None
    loja: Optional["LojaPublico"]


class TorneioJogadorPublico(TorneioBase):
    id: str
    pontuacao: float = 0
    status: StatusTorneio
    colocacao: int
    participantes: int
