from jose import jwt
from fastapi import Request
from datetime import datetime, timedelta, timezone
from app.core.config import settings
from app.models import Usuario
from app.core.security import fastmail
from fastapi_mail import MessageSchema


SECRET_KEY = settings.SECURITY_SECRET_KEY
ALGORITHM = settings.SECURITY_ALGORITHM


def criar_token_confirmacao(email: str):
    expiracao = datetime.now(timezone.utc) + timedelta(hours=24)
    token = jwt.encode({"sub": email, "exp": expiracao},
                       SECRET_KEY, algorithm=ALGORITHM)
    return token


async def processar_ativacao_usuario(
    usuario: Usuario,
    request: Request
):
    if settings.DEBUG:
        usuario.is_active = True
        return

    token = criar_token_confirmacao(usuario.email)
    link = f"{request.base_url}api/login/confirmar-email?token={token}"

    mensagem = MessageSchema(
        subject="Confirme seu email",
        recipients=[usuario.email],
        body=(
            "Olá!\n\n"
            "Obrigado por se cadastrar na TopDecked.\n"
            "Para ativar sua conta, confirme seu e-mail clicando no link abaixo:\n\n"
            f"{link}\n\n"
            "Se você não criou uma conta, ignore esta mensagem.\n\n"
            "Atenciosamente,\n"
            "Equipe TopDecked"
        ),
        subtype="plain"
    )

    await fastmail.send_message(mensagem)
