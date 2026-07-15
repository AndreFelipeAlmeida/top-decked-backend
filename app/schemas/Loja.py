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