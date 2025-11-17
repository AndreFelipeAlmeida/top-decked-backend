from typing import Optional, List, Dict
from app.schemas.JogadorTorneioLink import JogadorTorneioLinkPublico
from app.schemas.Loja import LojaPublico
from app.models import TorneioBase, RodadaBase, StatusTorneio
from datetime import date, time


class TorneioAtualizar(TorneioBase):
    nome: str | None = None
    descricao: str | None = None
    cidade: str | None = None
    estado: str | None = None
    tempo_por_rodada: int | None = None
    data_inicio: date | None = None
    vagas: int | None = None
    hora: time | None = None
    formato: str | None = None
    tipo: str | None = None
    taxa: float | None = None
    premio: str | None = None
    n_rodadas: int | None = None
    pontuacao_de_participacao: int | None = None
    regra_basica_id: int | None = None
    regras_adicionais: Optional[Dict[str, int]] | None = None


class TorneioPublico(TorneioBase):
    id: str
    status: StatusTorneio
    jogadores: List["JogadorTorneioLinkPublico"] | None
    rodadas: List["RodadaBase"] | None
    loja: Optional["LojaPublico"]


class TorneioJogadorPublico(TorneioBase):
    id: str
    pontuacao: float = 0
    status: StatusTorneio
    colocacao: int
    participantes: int