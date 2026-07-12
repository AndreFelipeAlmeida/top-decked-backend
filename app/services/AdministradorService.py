from sqlmodel import select

from app.core.config import settings
from app.core.db import SessionDep
from app.models import Administrador, Usuario
from app.utils.datetimeUtil import data_agora_brasil


def bootstrap_admin_root(session: SessionDep) -> None:
    """Roda no lifespan do backend. Idempotente — não faz nada se já existir
    algum Administrador cadastrado. Credenciais vêm só do .env
    (ADMIN_EMAIL/ADMIN_SENHA), nunca hardcoded no código."""
    if session.exec(select(Administrador)).first():
        return

    if not settings.ADMIN_EMAIL or not settings.ADMIN_SENHA:
        print(
            "[bootstrap_admin_root] ADMIN_EMAIL/ADMIN_SENHA não configurados no "
            ".env — nenhum Administrador inicial foi criado."
        )
        return

    novo_usuario = Usuario(
        email=settings.ADMIN_EMAIL,
        tipo="admin",
        is_active=True,
        data_cadastro=data_agora_brasil(),
    )
    novo_usuario.set_senha(settings.ADMIN_SENHA)
    session.add(novo_usuario)
    session.commit()
    session.refresh(novo_usuario)

    admin = Administrador(nome="Administrador", usuario_id=novo_usuario.id)
    session.add(admin)
    session.commit()
