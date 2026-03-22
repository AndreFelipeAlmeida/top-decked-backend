from sqlmodel import Field
from app.models import JogadorBase
from pydantic import BaseModel
from typing import List
from app.utils.Enums import MesEnum
from app.schemas.Torneio import TorneioJogadorPublico
from datetime import date
from app.schemas.Usuario import UsuarioPublico
from app.schemas.GameID import GameIDPublico

class JogadorPublico(JogadorBase):
    id: int
    usuario: UsuarioPublico | None
    tcgs: List[GameIDPublico] | None
    telefone: str | None
    data_nascimento: date | None


class LojaCriarJogador(BaseModel):
    nome: str
    game_id: GameIDPublico


class JogadorLojaPublico(BaseModel):
    id: int
    nome: str
    game_id: GameIDPublico
    creditos: float


class JogadorPublicoLoja(JogadorBase):
    id: int
    tcgs: List[GameIDPublico] | None
    tipo_jogador_id: int | None


class JogadorUpdate(JogadorBase):
    nome: str | None = None
    senha: str | None = None
    tcgs: List[GameIDPublico] | None
    telefone: str | None = None
    email: str | None = None
    data_nascimento: date | None = None


class JogadorCriar(BaseModel):
    nome: str | None = Field(default=None)
    email: str | None = Field(default=None)
    senha: str | None = Field(default=None)


class EstatisticasAnuais(BaseModel):
    mes: MesEnum
    ano: int
    pontos: float
    vitorias: int
    derrotas: int
    empates: int


class JogadorEstatisticas(BaseModel):
    torneio_totais: int
    taxa_vitoria: int = 0
    rank_geral: int
    rank_mensal: int
    rank_anual: int
    estatisticas_anuais: List["EstatisticasAnuais"]
    historico: List["TorneioJogadorPublico"]
