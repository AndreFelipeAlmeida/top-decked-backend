from sqlmodel import Field
from app.models import JogadorBase
from pydantic import BaseModel
from typing import List
from app.utils.Enums import MesEnum, TCG
from app.schemas.Torneio import TorneioJogadorPublico
from datetime import date
from app.schemas.Usuario import UsuarioPublico
from app.schemas.GameID import GameIDPublico
from app.schemas.JogadorCriado import JogadorCriadoPublico
from app.schemas.LojaJogadorLink import LojaJogadorPublico


class JogadorPublico(JogadorBase):
    id: int
    usuario: UsuarioPublico | None
    tcgs: List[JogadorCriadoPublico] = []
    telefone: str | None
    data_nascimento: date | None

class JogadorCompleto(JogadorPublico):
    lojas: list["LojaJogadorPublico"] = []

class PaginatedJogadorPublico(JogadorPublico):
    # LojaJogadorLink (a classe da tabela) não expõe relationships
    # (organizacoes/loja) como campos de pydantic — só LojaJogadorPublico (o
    # schema) declara isso de verdade. Sem isso, a tabela de "Gerenciar
    # Jogadores" nunca via se um jogador já era organizador nesta loja.
    lojas: List["LojaJogadorPublico"]
    
class PaginatedJogadores(BaseModel):
    data: list[PaginatedJogadorPublico]
    page: int
    limit: int
    total: int
    totalPages: int
    
    
class LojaCriarJogador(BaseModel):
    apelido: str
    game_id: GameIDPublico


class JogadorLojaPublico(BaseModel):
    id: int
    nome: str
    game_id: GameIDPublico
    creditos: float


class JogadorPublicoLoja(JogadorBase):
    id: int
    tcgs: List[JogadorCriadoPublico] | None
    tipo_jogador_id: int | None


class JogadorUpdate(JogadorBase):
    nome: str | None = None
    senha: str | None = None
    tcgs: List[GameIDPublico] | None = None
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


class ImpactoTrocaGameIdPublico(BaseModel):
    tcg: TCG
    game_id_atual: str | None
    torneios_importados: int


class JogadorEstatisticas(BaseModel):
    torneio_totais: int
    taxa_vitoria: int = 0
    rank_geral: int
    rank_mensal: int
    rank_anual: int
    estatisticas_anuais: List["EstatisticasAnuais"]
    historico: List["TorneioJogadorPublico"]
