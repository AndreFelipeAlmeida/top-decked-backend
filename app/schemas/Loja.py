from sqlmodel import Field
from app.models import LojaBase
from app.schemas.Usuario import UsuarioPublico
from app.utils.Enums import StatusAprovacaoLoja


class LojaPublicoTorneios(LojaBase):
    id: int
    usuario: UsuarioPublico
    n_torneios: int = 0
    status: StatusAprovacaoLoja
    slug: str
    # BRK-403: só preenchido quando quem chamou GET /lojas/ está autenticado
    # como jogador (Depends opcional, ver retornar_usuario_atual_opcional) —
    # TCGs que ELE organiza especificamente nesta loja. Lista vazia tanto
    # pra "não organiza aqui" quanto pra "não está logado".
    tcgs_organizados: list[str] = Field(default_factory=list)


class LojaPublico(LojaBase):
    id: int
    usuario: UsuarioPublico
    status: StatusAprovacaoLoja
    slug: str

class LojaCriar(LojaBase):
    email: str | None = Field(default=None)
    senha: str | None = Field(default=None)


class LojaAtualizar(LojaBase):
    nome: str | None = None
    endereco: str | None = None
    email: str | None = None
    senha: str | None = None
    telefone: str | None = None
    site: str | None = None