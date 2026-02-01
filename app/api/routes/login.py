from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse

from app.core.security import Token, autenticar, criar_token_de_acesso, ACCESS_TOKEN_EXPIRE_MINUTES, TokenData
from app.dependencies import retornar_usuario_atual

from typing import Annotated
from app.core.exception import TopDeckedException

from app.utils.UsuarioUtil import retornar_info_por_usuario
from app.core.db import SessionDep

from jose import jwt
from app.core.security import SECRET_KEY, ALGORITHM
from app.models import Usuario
from sqlmodel import select
import os

FRONTEND_URL = os.getenv("FRONTEND_URL")
FRONTEND_PORT = os.getenv("FRONTEND_PORT")

router = APIRouter(
    prefix="/login",
    tags=["Login"])


@router.post("/token")
async def login(
    formulario: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> Token:
    usuario = autenticar(formulario.username, formulario.password, session)

    dados = retornar_info_por_usuario(usuario, session)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = criar_token_de_acesso(
        dados=dados, delta_expiracao=access_token_expires
    )

    return Token(access_token=access_token, token_type="bearer")


@router.get("/profile")
async def ler_token(
        dados_token: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    return dados_token


@router.get("/confirmar-email")
def confirmar_email(token: str, session: SessionDep):

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload["sub"]
    except Exception:
        raise TopDeckedException.bad_request("Token inválido ou expirado")

    usuario = session.exec(select(Usuario).where(
        Usuario.email == email)).first()

    if not usuario:
        raise TopDeckedException.not_found("Usuário não encontrado")

    usuario.is_active = True
    session.commit()

    return RedirectResponse(url=F"http://{FRONTEND_URL}:{FRONTEND_PORT}", status_code=302)
