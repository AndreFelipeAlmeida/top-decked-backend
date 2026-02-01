from sqlmodel import Field
from app.models import LojaBase
from app.schemas.Usuario import UsuarioPublico


class LojaPublicoTorneios(LojaBase):
    id: int
    usuario: UsuarioPublico
    n_torneios: int = 0
    
    
class LojaPublico(LojaBase):
    id: int
    usuario: UsuarioPublico

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