import secrets
from datetime import timedelta

from fastapi import Response
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel

from sqlmodel import select

from app.models import Usuario, Loja
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.utils.datetimeUtil import agora_brasil
from app.utils.Enums import StatusAprovacaoLoja
from app.core.config import settings


SECRET_KEY = settings.SECURITY_SECRET_KEY
ALGORITHM = settings.SECURITY_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = int(settings.SECURITY_TOKEN_EXPIRATION)

OAUTH2_SCHEME = OAuth2PasswordBearer(tokenUrl="login/token", auto_error=False)
PWD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")

COOKIE_ACCESS_TOKEN = "access_token"
COOKIE_CSRF_TOKEN = "csrf_token"


def _cookie_domain() -> str | None:
    if settings.ROOT_DOMAIN in ("localhost", "127.0.0.1", "localtest.me"):
        return f".{settings.ROOT_DOMAIN}"
    return None if settings.DEBUG else f".{settings.ROOT_DOMAIN}"


def definir_cookies_sessao(response: Response, access_token: str) -> str:
    """Emite o cookie de sessão (HttpOnly) e o cookie de CSRF (legível por
    JS, de propósito — é ele que o frontend ecoa de volta no header
    X-CSRF-Token) no login. Retorna o csrf_token gerado, caso o chamador
    precise dele (não precisa hoje, mas evita um GET a mais só pra ler o
    cookie recém-setado em algum fluxo futuro)."""
    max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    domain = _cookie_domain()

    response.set_cookie(
        key=COOKIE_ACCESS_TOKEN,
        value=access_token,
        max_age=max_age,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="lax",
        domain=domain,
    )

    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=COOKIE_CSRF_TOKEN,
        value=csrf_token,
        max_age=max_age,
        httponly=False,
        secure=not settings.DEBUG,
        samesite="lax",
        domain=domain,
    )
    return csrf_token


def limpar_cookies_sessao(response: Response) -> None:
    # delete_cookie por baixo dos panos só reenvia o MESMO cookie com
    # Max-Age=0 — os atributos de segurança (httponly/secure/samesite)
    # precisam bater exatamente com os usados em definir_cookies_sessao,
    # senão o Set-Cookie de deleção não é reconhecido como o mesmo cookie
    # (visto na prática: sem httponly=True aqui, o browser/cliente HTTP
    # simplesmente ignora a tentativa de apagar o cookie HttpOnly
    # access_token, e o "logout" não desloga de verdade).
    domain = _cookie_domain()
    response.delete_cookie(
        COOKIE_ACCESS_TOKEN, domain=domain, httponly=True,
        secure=not settings.DEBUG, samesite="lax",
    )
    response.delete_cookie(
        COOKIE_CSRF_TOKEN, domain=domain, httponly=False,
        secure=not settings.DEBUG, samesite="lax",
    )


class Token(BaseModel):
    access_token: str
    token_type: str
    tipo: str | None = None
    slug: str | None = None


class TokenData(BaseModel):
    id: int | None = None
    tipo: str | None = None
    nome: str | None = None
    email: str | None = None
    usuario_id: int | None = None
    endereco: str | None = None
    slug: str | None = None


def verificar_senha(plain_password, hashed_password):
    return PWD_CONTEXT.verify(plain_password, hashed_password)


def retornar_senha_criptografada(password):
    return PWD_CONTEXT.hash(password)


def retornar_usuario_pelo_email(email: str, session: SessionDep) -> Usuario | None:
    consulta = select(Usuario).where(Usuario.email == email)
    usuario_atual = session.exec(consulta).first()
    return usuario_atual


def autenticar(email: str, forms_senha: str, session: SessionDep) -> Usuario | None:
    db_user = retornar_usuario_pelo_email(session=session, email=email)
    if not db_user or not verificar_senha(forms_senha, db_user.senha):
        raise TopDeckedException.unauthorized("E-mail ou senha incorretos.")
    if not db_user.is_active:
        raise TopDeckedException.bad_request(
            "Email não confirmado. Verifique sua caixa de entrada.")

    # Bloqueado aqui, no login, pra nunca emitir um token pra uma loja
    # pendente/rejeitada de aprovação.
    if db_user.tipo == "loja":
        loja = session.exec(select(Loja).where(Loja.usuario_id == db_user.id)).first()
        if loja and loja.status == StatusAprovacaoLoja.PENDENTE:
            raise TopDeckedException.forbidden(
                "Seu cadastro ainda está pendente de aprovação do administrador.")
        if loja and loja.status == StatusAprovacaoLoja.REJEITADA:
            raise TopDeckedException.forbidden(
                "Seu cadastro foi rejeitado pelo administrador.")

    return db_user


def criar_token_de_acesso(dados: dict, delta_expiracao: timedelta | None = None):
    criptografar = dados.copy()
    if delta_expiracao:
        expiracao = agora_brasil() + delta_expiracao
    else:
        expiracao = agora_brasil() + timedelta(minutes=15)
    criptografar.update({"exp": expiracao})
    encoded_jwt = jwt.encode(criptografar, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def validar_token(payload, session: SessionDep) -> bool:
    try:
        email = payload.get("email")
        if email is None:
            return False
    except InvalidTokenError:
        return False

    usuario = session.exec(select(Usuario).where(
        Usuario.email == email)).first()
    if usuario is None:
        return False
    return True
