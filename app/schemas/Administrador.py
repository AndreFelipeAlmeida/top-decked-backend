from app.models import AdministradorBase
from app.schemas.Usuario import UsuarioPublico


class AdministradorPublico(AdministradorBase):
    id: int
    usuario: UsuarioPublico
