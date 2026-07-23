from dotenv import load_dotenv
load_dotenv()

from jose import jwt
from datetime import datetime, timedelta, timezone

import resend

from app.core.config import settings
from app.models import Usuario


resend.api_key = settings.RESEND_API_KEY

SECRET_KEY = settings.SECURITY_SECRET_KEY
ALGORITHM = settings.SECURITY_ALGORITHM


def criar_token_confirmacao(email: str):
    expiracao = datetime.now(timezone.utc) + timedelta(hours=24)
    token = jwt.encode(
        {"sub": email, "exp": expiracao},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return token


async def processar_ativacao_usuario(usuario: Usuario):
    if settings.DEBUG:
        usuario.is_active = True
        return

    token = criar_token_confirmacao(usuario.email)
    link = f"{settings.FRONTEND_URL}/jogador/confirmar-email?token={token}"

    resend.Emails.send(
        {
            "from": f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM}>",
            "to": [usuario.email],
            "subject": "Confirme seu e-mail",
            "text": (
                "Olá!\n\n"
                "Obrigado por se cadastrar na Brickei.\n"
                "Para ativar sua conta, confirme seu e-mail clicando no link abaixo:\n\n"
                f"{link}\n\n"
                "Se você não criou uma conta, ignore esta mensagem.\n\n"
                "Atenciosamente,\n"
                "Equipe Brickei"
            ),
        }
    )


# "tipo" no payload separa esse token do de confirmação de e-mail acima —
# os dois só têm `sub`/`exp` em comum, então sem essa marca um link antigo
# de "confirme seu e-mail" (que pode ter ficado esquecido numa caixa de
# entrada por meses) poderia ser reaproveitado pra redefinir a senha de
# quem o recebeu. Validade curta (1h, contra as 24h da confirmação de
# e-mail) porque redefinição de senha é uma ação sensível.
TIPO_TOKEN_REDEFINICAO_SENHA = "redefinir_senha"


def criar_token_redefinicao_senha(email: str) -> str:
    expiracao = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode(
        {
            "sub": email,
            "tipo": TIPO_TOKEN_REDEFINICAO_SENHA,
            "exp": expiracao,
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return token


async def processar_esqueci_senha(usuario: Usuario) -> None:
    token = criar_token_redefinicao_senha(usuario.email)
    link = f"{settings.FRONTEND_URL}/redefinir-senha?token={token}"

    if settings.DEBUG:
        print(f"[DEBUG] Link de redefinição de senha para {usuario.email}: {link}")
        return

    resend.Emails.send(
        {
            "from": f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM}>",
            "to": [usuario.email],
            "subject": "Redefinição de senha",
            "text": (
                "Olá!\n\n"
                "Recebemos uma solicitação para redefinir a senha da sua conta na Brickei.\n"
                "Clique no link abaixo para escolher uma nova senha (válido por 1 hora):\n\n"
                f"{link}\n\n"
                "Se você não solicitou isso, ignore este e-mail — sua senha continua a mesma.\n\n"
                "Atenciosamente,\n"
                "Equipe Brickei"
            ),
        }
    )