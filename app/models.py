from sqlmodel import Field, SQLModel, Relationship, Enum, Column, DateTime, UniqueConstraint
from typing import List, Optional
import uuid
from datetime import datetime
from app.core.db import SessionDep
from app.utils.datetimeUtil import data_agora_brasil, agora_brasil
from app.utils.Enums import StatusTorneio, CategoriaItem, TCG, TipoTorneio, TipoMovimentacaoCredito, TipoMovimentacaoEstoque
from email_validator import validate_email, EmailNotValidError
from app.core.exception import TopDeckedException
from sqlmodel import select
from sqlalchemy import JSON, func
from passlib.context import CryptContext
from datetime import date, time


PWD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")
# ---------------------------------- Usuario ----------------------------------


class UsuarioBase(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    is_active: bool = Field(default=False)
    foto: Optional[str] = Field(default=None, unique=True)
    data_cadastro: date = Field(sa_column=Column(DateTime(timezone=True),
                                                 nullable=False, default=data_agora_brasil()
                                                 )
                                )


class Usuario(UsuarioBase, table=True):
    tipo: str = Field(index=True)
    senha: str = Field(index=True)

    def set_senha(self, senha_clara: str):
        self.senha = PWD_CONTEXT.hash(senha_clara)

    def set_email(self, email: str, session: SessionDep):
        try:
            valid = validate_email(email)
            num_usuarios = session.scalar(
                select(func.count(Usuario.id)).where(Usuario.email == email))

            if num_usuarios > 0:
                raise TopDeckedException.bad_request(
                    f"email cadastrado: '{email}'")

            self.email = email
        except EmailNotValidError:
            raise TopDeckedException.bad_request(f"e-mail inválido: '{email}'")


# ---------------------------------- Jogador ----------------------------------


class JogadorBase(SQLModel):
    nome: str
    telefone: str = Field(default=None, max_length=11, nullable=True)
    data_nascimento: date = Field(sa_column=Column(
        DateTime(timezone=True), nullable=True, default=None))


class Jogador(JogadorBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id",
                            nullable=True, ondelete="SET NULL")
    usuario: Usuario = Relationship(sa_relationship_kwargs={"lazy": "joined"})
    tcgs: List["GameID"] = Relationship(
        back_populates="jogador")
    torneios: List["JogadorTorneioLink"] = Relationship(
        back_populates="jogador")


# ---------------------------------- GameIDs ----------------------------------


class GameID(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("jogador_id", "tcg",
                         name="jogador_tcg_unique"),
    )
    id: Optional[str] = Field(default=None, primary_key=True)
    tcg: TCG = Field(nullable=False, default=TCG.POKEMON, primary_key=True)
    jogador_id: Optional[int] = Field(foreign_key="jogador.id", nullable=False)
    apelido: Optional[str] = Field(default=None)
    jogador: Optional["Jogador"] | None = Relationship(back_populates="tcgs")


# ---------------------------------- JogadorTorneioLink ----------------------------------
class JogadorTorneioLinkBase(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador_id: int | None = Field(
        default=None, foreign_key="jogador.id")
    tipo_jogador_id: int | None = Field(
        default=None, foreign_key="tipojogador.id")
    pontuacao: float = Field(default=0)
    pontuacao_com_regras: float = Field(default=0)
    apelido: Optional[str] = Field(default=None)


class JogadorTorneioLink(JogadorTorneioLinkBase, table=True):
    torneio_id: str | None = Field(
        default=None, foreign_key="torneio.id", ondelete="CASCADE")
    torneio: Optional["Torneio"] | None = Relationship(
        back_populates="jogadores")
    tipo_jogador: Optional["TipoJogador"] | None = Relationship()
    jogador: Optional["Jogador"] | None = Relationship(
        back_populates="torneios")
    gameid_importado: Optional[str] = Field(default=None)


# ---------------------------------- Loja ----------------------------------
class LojaBase(SQLModel):
    nome: str = Field(index=True)
    endereco: Optional[str] = Field(default=None, nullable=True)
    telefone: Optional[str] = Field(default=None, nullable=True)
    site: Optional[str] = Field(default=None, nullable=True)
    banner: Optional[str] = Field(default=None, unique=True)


class Loja(LojaBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", unique=True)
    usuario: Usuario = Relationship(sa_relationship_kwargs={"lazy": "joined"})
    torneios: List["Torneio"] = Relationship(back_populates="loja")


# ---------------------------------- Rodada ----------------------------------
class RodadaBase(SQLModel):
    jogador1_id: Optional[str] = Field(
        default=None, foreign_key="jogadortorneiolink.id", nullable=True)
    jogador2_id: Optional[str] = Field(
        default=None, foreign_key="jogadortorneiolink.id", nullable=True)
    vencedor: Optional[str] = Field(
        default=None, foreign_key="jogadortorneiolink.id", nullable=True)
    num_rodada: int = Field(default=None)
    mesa: Optional[int] = Field(default=None)
    data_de_inicio: date = Field(sa_column=Column(
        DateTime(timezone=True), nullable=True), default=None)
    finalizada: Optional[bool] = Field(default=False)


class Rodada(RodadaBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    torneio_id: str = Field(
        default=None, foreign_key="torneio.id", ondelete="CASCADE")


# ---------------------------------- TipoJogador ----------------------------------
class TipoJogadorBase(SQLModel):
    nome: str = Field(default=None)
    pt_vitoria: float = Field(default=None)
    pt_derrota: float = Field(default=None)
    pt_empate: float = Field(default=None)
    pt_oponente_perde: float = Field(default=None)
    pt_oponente_ganha: float = Field(default=None)
    pt_oponente_empate: float = Field(default=None)
    tcg: str = Field(default=None)


class TipoJogador(TipoJogadorBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    loja: int | None = Field(default=None, foreign_key="loja.id")


# ---------------------------------- Torneio ----------------------------------


class TorneioBase(SQLModel):
    nome: Optional[str] = Field(default=None, nullable=True)
    descricao: Optional[str] = Field(default=None, nullable=True)
    cidade: Optional[str] = Field(default=None, index=True, nullable=True)
    estado: Optional[str] = Field(default=None, index=True, nullable=True)
    tempo_por_rodada: int = Field(default=30, index=True)
    data_inicio: date = Field(sa_column=Column(
        DateTime(timezone=True), nullable=False), default=None)
    vagas: int = Field(default=0)
    hora: Optional[time] = Field(default=None, nullable=True)
    formato: Optional[str] = Field(default="Desconhecido", nullable=True)
    tcg: Optional[TCG] = Field(default=TCG.POKEMON, nullable=False)
    tipo: Optional[TipoTorneio] = Field(
        default=TipoTorneio.IMPORTADO, nullable=False)
    taxa: float = Field(default=0)
    premio: Optional[str] = Field(default=None, nullable=True)
    n_rodadas: int = Field(default=0)
    rodada_atual: int = Field(default=0)
    regra_basica_id: Optional[int] = Field(
        default=None, foreign_key="tipojogador.id", nullable=True)
    pontuacao_de_participacao: int = Field(default=0)


class Torneio(TorneioBase, table=True):
    id: Optional[str] = Field(
        default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    loja_id: int = Field(foreign_key="loja.id", nullable=True)
    loja: Optional["Loja"] = Relationship(
        back_populates="torneios", sa_relationship_kwargs={"lazy": "joined"})
    rodadas: List["Rodada"] = Relationship(
        sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    jogadores: List["JogadorTorneioLink"] = Relationship(back_populates="torneio",
                                                         sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    status: StatusTorneio = Field(sa_column=Column(
        Enum(StatusTorneio)), default=StatusTorneio.ABERTO)
    regra_basica: Optional["TipoJogador"] = Relationship()


# ---------------------------------- Estoque ----------------------------------


class EstoqueBase(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True)
    loja_id: int | None = Field(
        default=None, foreign_key="loja.id")
    nome: str = Field(default=None)
    categoria: CategoriaItem = Field(sa_column=Column(
        Enum(CategoriaItem)), default=CategoriaItem.GERAIS)
    preco: float = Field(default=0)
    min_quantidade: int = Field(default=0)
    
class Estoque(EstoqueBase, table=True):
    quantidade: int = Field(default=0)


# ---------------------------------- Histórico do Estoque ----------------------------------


class HistoricoEstoque(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    estoque_id: Optional[int] = Field(foreign_key="estoque.id")
    loja_id: int = Field(foreign_key="loja.id")

    # movimentação
    quantidade: Optional[int] = Field(default=None)
    tipo: TipoMovimentacaoEstoque

    # log de alteração
    campo_alterado: Optional[str] = None
    valor_antigo: Optional[str] = None
    valor_novo: Optional[str] = None

    transacao_id: Optional[int] = Field(
        default=None, foreign_key="transacao.id")

    descricao: Optional[str] = None
    criado_em: datetime = Field(default_factory=agora_brasil)
    
    
# ---------------------------------- JogadorLojaLink ----------------------------------


class LojaJogadorLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador_id: Optional[int] = Field(
        default=None, foreign_key="jogador.id")
    loja_id: int | None = Field(
        default=None, foreign_key="loja.id")
    creditos: float = Field(default=0)
    apelido: Optional[str] = Field(default=None)
    game_id: Optional[str] = Field(default=None)
    tcg: Optional[TCG] = Field(default=None)


# ---------------------------------- Histórico de Crédito ----------------------------------


class HistoricoCredito(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador_id: int = Field(foreign_key="jogador.id")
    loja_id: int = Field(foreign_key="loja.id")
    valor_antigo: Optional[float] = Field(default=None)
    valor_novo: Optional[float] = Field(default=None)
    tipo: TipoMovimentacaoCredito
    descricao: Optional[str] = None
    transacao_id: Optional[int] = Field(
        default=None, foreign_key="transacao.id")
    criado_em: datetime = Field(default_factory=agora_brasil())
    
    
# ---------------------------------- Transações ----------------------------------


class Transacao(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador_id: int | None = Field(
        default=None, foreign_key="jogador.id")
    loja_id: int | None = Field(
        default=None, foreign_key="loja.id")
    itens: List["ItemTransacao"] = Relationship(back_populates="transacao")
    
    
# ---------------------------------- Item Transação ----------------------------------


class ItemTransacao(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    transacao_id: int = Field(
        default=None, foreign_key="transacao.id")
    transacao: Optional["Transacao"] | None = Relationship(
        back_populates="itens")
    item_id: Optional[int] = Field(
        default=None, foreign_key="estoque.id")
    quantidade: int = Field(default=0)
    nome_item: str = Field(default="")
    preco_unitario: float = Field(default=0)