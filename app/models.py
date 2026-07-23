from sqlmodel import Field, SQLModel, Relationship, Enum, Column, Date, DateTime, UniqueConstraint
from typing import List, Optional
import uuid
from datetime import datetime
from app.core.db import SessionDep
from app.utils.datetimeUtil import data_agora_brasil, agora_brasil
from app.utils.Enums import StatusTorneio, StatusAprovacaoLoja, TCG, FormatoTorneio, FormatoMD, TipoTorneio, TipoParticipanteTorneio, MotivoPontuacaoExtra, TipoRegraPontuacaoEvento, TipoMovimentacaoCredito, TipoMovimentacaoItem, CategoriaConquista
from email_validator import validate_email, EmailNotValidError
from app.core.exception import TopDeckedException
from sqlmodel import select
from sqlalchemy import func
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
                select(func.count(Usuario.id)).where(
                    Usuario.email == email, Usuario.id != self.id))

            if num_usuarios > 0:
                raise TopDeckedException.bad_request(
                    f"email cadastrado: '{email}'")

            self.email = valid.normalized
        except EmailNotValidError:
            raise TopDeckedException.bad_request(f"e-mail inválido: '{email}'")


# ---------------------------------- Jogador ----------------------------------


class JogadorBase(SQLModel):
    nome: str
    telefone: str = Field(default=None, max_length=11, nullable=True)
    # Só a data (dia), sem hora nem timezone — era DateTime(timezone=True)
    # antes, o mesmo bug de Torneio.data_planejada: o timestamp gravado num
    # fuso podia virar outro dia ao ser lido/exibido em outro (idade e
    # categoria calculadas errado perto da virada de mês/ano). Date elimina
    # essa ambiguidade de vez.
    data_nascimento: date = Field(sa_column=Column(
        Date, nullable=True, default=None))


class Jogador(JogadorBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id",
                            nullable=True, ondelete="SET NULL")
    usuario: Usuario = Relationship(sa_relationship_kwargs={"lazy": "joined"})
    tcgs: List["JogadorCriado"] = Relationship(
        back_populates="jogador")
    lojas: List["LojaJogadorLink"] = Relationship(
        back_populates="jogador",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"})

# ---------------------------------- JogadorCriado ----------------------------------


class JogadorCriado(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("game_id", "tcg",
                         name="jogador_criado_game_id_tcg_unique"),
        UniqueConstraint("jogador_id", "tcg",
                         name="jogador_criado_jogador_tcg_unique"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    game_id: str
    tcg: TCG = Field(nullable=False, default=TCG.POKEMON)
    apelido: Optional[str] = Field(default=None)
    jogador_id: Optional[int] = Field(default=None, foreign_key="jogador.id")
    data_nascimento: Optional[date] = Field(default=None)
    jogador: Optional["Jogador"] | None = Relationship(back_populates="tcgs")


# ---------------------------------- JogadorTorneioLink ----------------------------------

class JogadorTorneioLinkBase(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador_criado_id: int = Field(
        foreign_key="jogadorcriado.id")
    regra_extra_id: int | None = Field(
        default=None, foreign_key="tipojogador.id")
    tipo: TipoParticipanteTorneio = Field(
        default=TipoParticipanteTorneio.JOGADOR, nullable=False)
    pontuacao: float = Field(default=0)
    pontuacao_com_regras: float = Field(default=0)
    apelido: Optional[str] = Field(default=None)
    composicao_representacao_id: int | None = Field(
        default=None, foreign_key="representacaocomposicao.id")
    vitorias: int = Field(default=0)
    derrotas: int = Field(default=0)
    empates: int = Field(default=0)
    byes: int = Field(default=0)
    porcentagem_vitorias_oponentes: Optional[float] = Field(default=None)
    porcentagem_vitorias_oponentes_oponentes: Optional[float] = Field(default=None)


class JogadorTorneioLink(JogadorTorneioLinkBase, table=True):
    # Um jogador tem NO MÁXIMO uma linha por torneio — fonte única de
    # verdade (ver TipoParticipanteTorneio.JOGADOR_E_JUIZ, o valor usado
    # quando ele acumula os dois papéis, em vez de duas linhas separadas).
    __table_args__ = (
        UniqueConstraint("jogador_criado_id", "torneio_id",
                          name="uix_jogador_torneio"),
    )
    torneio_id: str | None = Field(
        default=None, foreign_key="torneio.id", ondelete="CASCADE")
    loja_id: int = Field(foreign_key="loja.id", index=True)
    torneio: Optional["Torneio"] | None = Relationship(
        back_populates="jogadores")
    regra_extra: Optional["TipoJogador"] | None = Relationship()
    composicao_representacao: Optional["RepresentacaoComposicao"] = Relationship()
    composicao_unidades: List["JogadorComposicaoUnidade"] = Relationship(
        back_populates="link",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    jogador_criado: Optional["JogadorCriado"] = Relationship()

    rodadas_como_jogador1: list["Rodada"] = Relationship(
        back_populates="jogador1",
        sa_relationship_kwargs={
            "foreign_keys": lambda: [Rodada.jogador1_id]
        }
    )

    rodadas_como_jogador2: list["Rodada"] = Relationship(
        back_populates="jogador2",
        sa_relationship_kwargs={
            "foreign_keys": lambda: [Rodada.jogador2_id]
        }
    )

    rodadas_vencidas: list["Rodada"] = Relationship(
        back_populates="vencedor",
        sa_relationship_kwargs={
            "foreign_keys": lambda: [Rodada.vencedor_id]
        }
    )

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
    # Status de aprovação nunca é aceito do cliente — por isso não mora em
    # LojaBase (que alimenta LojaCriar/LojaAtualizar); só o Administrador
    # muda isso.
    status: StatusAprovacaoLoja = Field(
        sa_column=Column(Enum(StatusAprovacaoLoja)), default=StatusAprovacaoLoja.PENDENTE)
    slug: str = Field(unique=True, index=True)


# ---------------------------------- Administrador ----------------------------------
# Conta de governança global da plataforma — segue o mesmo padrão de
# Jogador/Loja (perfil 1:1 ligado a um Usuario, que segura email/senha/
# is_active/tipo).
class AdministradorBase(SQLModel):
    nome: str


class Administrador(AdministradorBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", unique=True)
    usuario: Usuario = Relationship(sa_relationship_kwargs={"lazy": "joined"})


# ---------------------------------- Rodada ----------------------------------
class RodadaBase(SQLModel):
    jogador1_id: Optional[int] = Field(
        default=None, foreign_key="jogadortorneiolink.id", nullable=True)
    jogador2_id: Optional[int] = Field(
        default=None, foreign_key="jogadortorneiolink.id", nullable=True)
    vencedor_id: Optional[int] = Field(
        default=None, foreign_key="jogadortorneiolink.id", nullable=True)
    num_rodada: int = Field(default=None)
    mesa: Optional[int] = Field(default=None)
    data_de_inicio: datetime = Field(sa_column=Column(
        DateTime(timezone=True), nullable=True), default=None)
    finalizada: Optional[bool] = Field(default=False)


class Rodada(RodadaBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    torneio_id: str = Field(
        default=None, foreign_key="torneio.id", ondelete="CASCADE")
    loja_id: int = Field(foreign_key="loja.id", index=True)

    jogador1: Optional["JogadorTorneioLink"] = Relationship(
        back_populates="rodadas_como_jogador1",
        sa_relationship_kwargs={
            "foreign_keys": lambda: [Rodada.jogador1_id]
        }
    )

    jogador2: Optional["JogadorTorneioLink"] = Relationship(
        back_populates="rodadas_como_jogador2",
        sa_relationship_kwargs={
            "foreign_keys": lambda: [Rodada.jogador2_id]
        }
    )

    vencedor: Optional["JogadorTorneioLink"] = Relationship(
        back_populates="rodadas_vencidas",
        sa_relationship_kwargs={
            "foreign_keys": lambda: [Rodada.vencedor_id]
        }
    )

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
    loja_id: int | None = Field(default=None, foreign_key="loja.id")


# ---------------------------------- Temporada ----------------------------------


class TemporadaBase(SQLModel):
    tcg: TCG
    nome: Optional[str] = Field(default=None)
    ano_inicio: int
    mes_inicio: int
    ano_fim: int
    mes_fim: int


class Temporada(TemporadaBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    loja_id: int = Field(foreign_key="loja.id")


# ---------------------------------- Torneio ----------------------------------


class TorneioBase(SQLModel):
    nome: Optional[str] = Field(default=None, nullable=True)
    descricao: Optional[str] = Field(default=None, nullable=True)
    cidade: Optional[str] = Field(default=None, index=True, nullable=True)
    estado: Optional[str] = Field(default=None, index=True, nullable=True)
    tempo_por_rodada: int = Field(default=30, index=True)
    # Só a data (dia), sem hora nem timezone — hora_planejada é um campo
    # separado. Era DateTime(timezone=True) antes, o que causava o torneio
    # "perder um dia" perto da virada de mês em fusos negativos (o
    # timestamp gravado num fuso virava outro dia ao ser lido/exibido em
    # outro); Date elimina essa ambiguidade de vez.
    data_planejada: date = Field(sa_column=Column(
        Date, nullable=False), default=None)
    vagas: int = Field(default=0)
    hora_planejada: Optional[time] = Field(default=None, nullable=True)
    formato: Optional[FormatoTorneio] = Field(default=None, nullable=True)
    melhor_de: FormatoMD = Field(default=FormatoMD.MD1, nullable=False)
    jogo: Optional[TCG] = Field(default=TCG.POKEMON, nullable=False)
    tipo: Optional[TipoTorneio] = Field(
        default=TipoTorneio.IMPORTADO, nullable=False)
    taxa: float = Field(default=0)
    premio: Optional[str] = Field(default=None, nullable=True)
    n_rodadas: int = Field(default=0)
    rodada_atual: int = Field(default=0)
    regra_basica_id: Optional[int] = Field(
        default=None, foreign_key="tipojogador.id", nullable=True)
    pontuacao_de_participacao: int = Field(default=0)
    # Momento real (não planejado) em que o torneio começou/terminou — usados
    # para calcular a conquista "horas jogadas". Preenchidos automaticamente
    # na importação (ver ImportacaoService) e editáveis manualmente pelo organizador.
    inicio_real: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    fim_real: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    # Se este torneio deve contar pros pontos automáticos dos Eventos ativos
    # no período dele. Default True — o organizador desmarca só pra casos
    # pontuais (ex.: um torneio amistoso que não deveria valer pontuação).
    conta_em_eventos: bool = Field(default=True, nullable=False)


class Torneio(TorneioBase, table=True):
    id: Optional[str] = Field(
        default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    loja_id: int = Field(foreign_key="loja.id", nullable=True)
    loja: Optional["Loja"] = Relationship(
        back_populates="torneios", sa_relationship_kwargs={"lazy": "joined"})
    rodadas: List["Rodada"] = Relationship(
        sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    # order_by explícito: sem isso, a ordem de retorno de uma relação
    # um-para-muitos não é garantida pelo banco e pode mudar sozinha a
    # qualquer UPDATE na linha, fazendo o jogador "pular" de posição na
    # listagem.
    jogadores: List["JogadorTorneioLink"] = Relationship(back_populates="torneio",
                                                         sa_relationship_kwargs={
                                                             "cascade": "all, delete-orphan",
                                                             "order_by": "JogadorTorneioLink.id",
                                                         })
    status: StatusTorneio = Field(sa_column=Column(
        Enum(StatusTorneio)), default=StatusTorneio.ABERTO)
    regra_basica: Optional["TipoJogador"] = Relationship()


# ---------------------------------- PontuacaoExtra ----------------------------------


class PontuacaoExtraBase(SQLModel):
    jogador_criado_id: int = Field(foreign_key="jogadorcriado.id")
    motivo: MotivoPontuacaoExtra
    descricao: Optional[str] = Field(default=None)
    pontos: float


class PontuacaoExtra(PontuacaoExtraBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    torneio_id: str = Field(foreign_key="torneio.id", ondelete="CASCADE")
    loja_id: int = Field(foreign_key="loja.id", index=True)
    criado_em: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=agora_brasil)
    torneio: Optional["Torneio"] = Relationship()
    jogador_criado: Optional["JogadorCriado"] = Relationship()


# ---------------------------------- Evento ----------------------------------


class EventoBase(SQLModel):
    tcg: TCG
    nome: str
    descricao: Optional[str] = Field(default=None)
    data_inicio: date
    data_fim: date


class Evento(EventoBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    loja_id: int = Field(foreign_key="loja.id")
    loja: Optional["Loja"] = Relationship()
    metas: List["MetaEvento"] = Relationship(
        back_populates="evento", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    regras: List["RegraPontuacaoEvento"] = Relationship(
        back_populates="evento", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    participantes: List["ParticipanteEvento"] = Relationship(
        back_populates="evento", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    pontos_manuais: List["PontosManualEvento"] = Relationship(
        back_populates="evento", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    regras_manuais: List["RegraPontuacaoManualEvento"] = Relationship(
        back_populates="evento", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class MetaEventoBase(SQLModel):
    pontos_necessarios: int
    recompensa_descricao: Optional[str] = Field(default=None)
    recompensa_imagem_url: Optional[str] = Field(default=None)


class MetaEvento(MetaEventoBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    evento_id: int = Field(foreign_key="evento.id", ondelete="CASCADE")
    evento: Optional["Evento"] = Relationship(back_populates="metas")


class RegraPontuacaoEventoBase(SQLModel):
    tipo: TipoRegraPontuacaoEvento
    pontos: float


class RegraPontuacaoEvento(RegraPontuacaoEventoBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    evento_id: int = Field(foreign_key="evento.id", ondelete="CASCADE")
    evento: Optional["Evento"] = Relationship(back_populates="regras")


# Vitrine de regras de Pontuação Manual do evento: puramente informativo (o
# jogador vê "como" pode ganhar pontos extras), sem nenhum efeito automático
# na pontuação — quem lança os pontos de fato continua sendo o organizador,
# via PontosManualEvento.
class RegraPontuacaoManualEventoBase(SQLModel):
    descricao: str
    pontos: float


class RegraPontuacaoManualEvento(RegraPontuacaoManualEventoBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    evento_id: int = Field(foreign_key="evento.id", ondelete="CASCADE")
    evento: Optional["Evento"] = Relationship(back_populates="regras_manuais")


class ParticipanteEventoBase(SQLModel):
    jogador_criado_id: int = Field(foreign_key="jogadorcriado.id")


class ParticipanteEvento(ParticipanteEventoBase, table=True):
    __table_args__ = (
        UniqueConstraint("evento_id", "jogador_criado_id", name="evento_id_jogador_criado_id_unique"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    evento_id: int = Field(foreign_key="evento.id", ondelete="CASCADE")
    evento: Optional["Evento"] = Relationship(back_populates="participantes")
    jogador_criado: Optional["JogadorCriado"] = Relationship()


class PontosManualEventoBase(SQLModel):
    jogador_criado_id: int = Field(foreign_key="jogadorcriado.id")
    descricao: str
    pontos: float


class PontosManualEvento(PontosManualEventoBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    evento_id: int = Field(foreign_key="evento.id", ondelete="CASCADE")
    criado_em: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=agora_brasil)
    evento: Optional["Evento"] = Relationship(back_populates="pontos_manuais")
    jogador_criado: Optional["JogadorCriado"] = Relationship()


# ---------------------------------- Categoria de Item ----------------------------------

class Categoria(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    loja_id: int | None = Field(
        default=None, foreign_key="loja.id")
    nome: str = Field(default=None)


# ---------------------------------- Item ----------------------------------


class ItemBase(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True)
    loja_id: int | None = Field(
        default=None, foreign_key="loja.id")
    nome: str = Field(default=None)
    categoria: int = Field(
        default=None, nullable=False, foreign_key="categoria.id")
    preco: float = Field(default=0)
    min_quantidade: int = Field(default=0)
    is_vendavel: bool = Field(default=True, nullable=False)


class Item(ItemBase, table=True):
    quantidade: int = Field(default=0)


# ---------------------------------- Histórico de Itens ----------------------------------


class HistoricoItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    item_id: Optional[int] = Field(foreign_key="item.id")
    loja_id: int = Field(foreign_key="loja.id")

    # movimentação
    quantidade: Optional[int] = Field(default=None)
    tipo: TipoMovimentacaoItem

    # log de alteração
    campo_alterado: Optional[str] = None
    valor_antigo: Optional[str] = None
    valor_novo: Optional[str] = None

    transacao_id: Optional[int] = Field(
        default=None, foreign_key="transacao.id")

    descricao: Optional[str] = None
    criado_em: datetime = Field(default_factory=agora_brasil)


# ---------------------------------- JogadorLojaLink ----------------------------------


class LojaJogadorLinkBase(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador_id: int = Field(foreign_key="jogador.id")
    loja_id: int | None = Field(
        default=None, foreign_key="loja.id")
    creditos: float = Field(default=0)
    apelido: Optional[str] = Field(default=None)


class LojaJogadorLink(LojaJogadorLinkBase, table=True):
    __table_args__ = (
        UniqueConstraint("loja_id", "jogador_id",
                         name="loja_id_jogador_id_unique"),
    )
    organizacoes: List["LojaJogadorOrganizadorTCG"] = Relationship()
    jogador: Optional["Jogador"] = Relationship(back_populates="lojas")
    loja: Optional["Loja"] = Relationship()
    
# ---------------------------------- Histórico de Crédito ----------------------------------

class LojaJogadorOrganizadorTCG(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "loja_jogador_link_id",
            "tcg",
            name="unique_organizador_tcg"
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    loja_jogador_link_id: int = Field(
        foreign_key="lojajogadorlink.id"
    )
    tcg: TCG = Field(nullable=False)
    loja_jogador_link: "LojaJogadorLink" = Relationship()
    
# ---------------------------------- Histórico de Crédito ----------------------------------


class HistoricoCredito(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador_id: Optional[int] = Field(
        default=None, foreign_key="jogador.id", nullable=True)
    loja_id: int = Field(foreign_key="loja.id")
    valor_antigo: Optional[float] = Field(default=None)
    valor_novo: Optional[float] = Field(default=None)
    tipo: TipoMovimentacaoCredito
    descricao: Optional[str] = None
    transacao_id: Optional[int] = Field(
        default=None, foreign_key="transacao.id")
    criado_em: datetime = Field(default_factory=agora_brasil)


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
    transacao: Optional["Transacao"] = Relationship(
        back_populates="itens")
    item_id: Optional[int] = Field(
        default=None, foreign_key="item.id")
    quantidade: int = Field(default=0)
    nome_item: str = Field(default="")
    preco_unitario: float = Field(default=0)


# ---------------------------------- Conquista ----------------------------------


class ConquistaBase(SQLModel):
    codigo: str = Field(index=True, unique=True)
    nome: str
    descricao: str
    categoria: CategoriaConquista = Field(index=True)
    icone: str
    tcg: Optional[TCG] = Field(default=None)
    ativa: bool = Field(default=True)


class Conquista(ConquistaBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    criado_em: datetime = Field(default_factory=agora_brasil)
    niveis: List["ConquistaNivel"] = Relationship(back_populates="conquista")


class ConquistaNivel(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("conquista_id", "nivel", name="conquista_nivel_unique"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    conquista_id: int = Field(foreign_key="conquista.id")
    nivel: int
    nome_nivel: str
    meta: float
    conquista: Optional["Conquista"] = Relationship(back_populates="niveis")


class JogadorConquistaBase(SQLModel):
    jogador_id: int = Field(foreign_key="jogador.id")
    conquista_id: int = Field(foreign_key="conquista.id")
    progresso_atual: float = Field(default=0)
    nivel_atual: int = Field(default=0)
    nivel_atual_em: Optional[datetime] = Field(default=None)


class JogadorConquista(JogadorConquistaBase, table=True):
    __table_args__ = (
        UniqueConstraint("jogador_id", "conquista_id", name="jogador_conquista_unique"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador: Optional["Jogador"] = Relationship()
    conquista: Optional["Conquista"] = Relationship()


class HistoricoConquistaBase(SQLModel):
    jogador_id: int = Field(foreign_key="jogador.id")
    conquista_id: int = Field(foreign_key="conquista.id")
    nivel: int
    progresso_no_momento: float
    conquistado_em: datetime = Field(default_factory=agora_brasil)


class HistoricoConquista(HistoricoConquistaBase, table=True):
    __table_args__ = (
        UniqueConstraint("jogador_id", "conquista_id", "nivel", name="historico_conquista_unique"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador: Optional["Jogador"] = Relationship()
    conquista: Optional["Conquista"] = Relationship()


# ---------------------------------- Composições ----------------------------------

class UnidadeCatalogo(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("tcg", "external_id", name="unidade_catalogo_unique"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    tcg: TCG = Field(index=True)
    external_id: int = Field(index=True)
    nome: str = Field(index=True)
    manual: bool = Field(default=False)


class CatalogoAtualizacao(SQLModel, table=True):
    """Controla quando o catálogo de cada TCG foi buscado pela última vez, pra
    decidir se é hora de re-buscar (ver PokemonCatalogoService.garantir_catalogo_atualizado).
    Precisa de timezone=True na coluna — sem isso o SQLite devolve o datetime
    sem tzinfo na leitura, e a subtração com agora_brasil() (tz-aware) quebra."""
    tcg: TCG = Field(primary_key=True)
    atualizado_em: datetime = Field(
        sa_column=Column(DateTime(timezone=True)),
        default_factory=agora_brasil,
    )


class RepresentacaoComposicaoBase(SQLModel):
    tcg: TCG = Field(index=True)
    nome: str = Field(index=True)


class RepresentacaoComposicao(RepresentacaoComposicaoBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    criado_em: datetime = Field(default_factory=agora_brasil)
    unidades: List["RepresentacaoComposicaoUnidade"] = Relationship(
        back_populates="representacao",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "RepresentacaoComposicaoUnidade.ordem",
        },
    )


class RepresentacaoComposicaoUnidade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    representacao_id: int = Field(
        foreign_key="representacaocomposicao.id", ondelete="CASCADE")
    ordem: int
    unidade_catalogo_id: int = Field(foreign_key="unidadecatalogo.id")
    unidade: Optional["UnidadeCatalogo"] = Relationship()
    representacao: Optional["RepresentacaoComposicao"] = Relationship(
        back_populates="unidades")


# Uma linha da composição completa de um jogador numa participação específica —
# uma unidade do catálogo + quantidade (ex.: "4x Pikachu"). Distinta da
# RepresentacaoComposicaoUnidade (que é só o ícone de 2 unidades do arquétipo).
class JogadorComposicaoUnidadeBase(SQLModel):
    unidade_catalogo_id: int = Field(foreign_key="unidadecatalogo.id")
    quantidade: int = Field(default=1)


class JogadorComposicaoUnidade(JogadorComposicaoUnidadeBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    jogador_torneio_link_id: int = Field(
        foreign_key="jogadortorneiolink.id", ondelete="CASCADE")
    unidade: Optional["UnidadeCatalogo"] = Relationship()
    link: Optional["JogadorTorneioLink"] = Relationship(
        back_populates="composicao_unidades")


class ComposicaoPartida(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    criado_em: datetime = Field(default_factory=agora_brasil)
    unidades: List["ComposicaoPartidaUnidade"] = Relationship(
        back_populates="composicao_partida",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class ComposicaoPartidaUnidade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    composicao_partida_id: int = Field(
        foreign_key="composicaopartida.id", ondelete="CASCADE")
    unidade_catalogo_id: int = Field(foreign_key="unidadecatalogo.id")
    quantidade: int = Field(default=1)
    unidade: Optional["UnidadeCatalogo"] = Relationship()
    composicao_partida: Optional["ComposicaoPartida"] = Relationship(
        back_populates="unidades")


class RodadaComposicaoBase(SQLModel):
    rodada_id: int = Field(foreign_key="rodada.id", ondelete="CASCADE")
    jogador_torneio_link_id: int = Field(
        foreign_key="jogadortorneiolink.id", ondelete="CASCADE")
    composicao_partida_id: int = Field(foreign_key="composicaopartida.id")


class RodadaComposicao(RodadaComposicaoBase, table=True):
    """Liga uma participação (JogadorTorneioLink) numa rodada específica à
    ComposicaoPartida usada nela — único por (rodada, participação), já que
    cada lado de uma rodada tem sua própria composição de partida."""
    __table_args__ = (
        UniqueConstraint("rodada_id", "jogador_torneio_link_id",
                         name="rodada_composicao_unique"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    composicao_partida: Optional["ComposicaoPartida"] = Relationship()
