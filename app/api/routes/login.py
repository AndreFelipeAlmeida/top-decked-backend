from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse

from app.core.security import (
    Token, autenticar, criar_token_de_acesso, ACCESS_TOKEN_EXPIRE_MINUTES, TokenData,
    definir_cookies_sessao, limpar_cookies_sessao,
)
from app.dependencies import retornar_usuario_atual

from typing import Annotated
from app.core.exception import TopDeckedException

from app.services.UsuarioService import retornar_info_por_usuario
from app.services.EmailService import processar_esqueci_senha, TIPO_TOKEN_REDEFINICAO_SENHA
from app.core.db import SessionDep

from jose import jwt
from jose.exceptions import JOSEError
from app.core.security import SECRET_KEY, ALGORITHM
from app.models import Usuario
from app.schemas.Login import EsqueciSenhaDTO, RedefinirSenhaDTO
from sqlmodel import select
from app.core.config import settings


router = APIRouter(
    prefix="/login",
    tags=["Login"])


def _decodificar_token_redefinicao(token: str, session: SessionDep) -> Usuario:
    """Compartilhado pelas duas rotas de redefinição abaixo — valida
    assinatura/validade do token E que ele foi emitido com o propósito certo
    (`tipo`), não só o de confirmação de e-mail (ver EmailService.py)."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("tipo") != TIPO_TOKEN_REDEFINICAO_SENHA:
            raise TopDeckedException.bad_request("Token inválido ou expirado.")
        email = payload["sub"]
    except HTTPException:
        raise
    except JOSEError:
        raise TopDeckedException.bad_request("Token inválido ou expirado.")

    usuario = session.exec(select(Usuario).where(Usuario.email == email)).first()
    if not usuario:
        raise TopDeckedException.bad_request("Token inválido ou expirado.")

    return usuario


@router.post("/token")
async def login(
    formulario: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep, response: Response
) -> Token:
    usuario = autenticar(formulario.username, formulario.password, session)

    dados = retornar_info_por_usuario(usuario, session)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = criar_token_de_acesso(
        dados=dados, delta_expiracao=access_token_expires
    )

    # BRK-309: cookie transversal (Domain=.brickei.com.br em produção) é a
    # forma primária de sessão agora — access_token no corpo da resposta
    # continua existindo só pra clientes não-browser (scripts, mobile) que
    # não têm como usar cookie automaticamente.
    definir_cookies_sessao(response, access_token)

    return Token(
        access_token=access_token,
        token_type="bearer",
        tipo=dados["tipo"],
        slug=dados.get("slug"),
    )


@router.post("/logout")
async def logout(response: Response):
    """BRK-309: precisa de um endpoint de verdade porque o cookie de
    sessão é HttpOnly — JS no frontend não consegue apagá-lo sozinho."""
    limpar_cookies_sessao(response)
    return {"detail": "Sessão encerrada."}


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

    return RedirectResponse(url=settings.FRONTEND_URL, status_code=302)


@router.post("/esqueci-senha")
async def esqueci_senha(dados: EsqueciSenhaDTO, session: SessionDep):
    usuario = session.exec(select(Usuario).where(Usuario.email == dados.email)).first()

    # Sempre a mesma mensagem, exista ou não o e-mail — senão a resposta
    # vira um jeito de descobrir quais e-mails estão cadastrados na
    # plataforma (só envia de verdade quando `usuario` existe).
    if usuario:
        await processar_esqueci_senha(usuario)

    return {
        "detail": "Se este e-mail estiver cadastrado, você receberá um link para redefinir sua senha."
    }


@router.get("/validar-token-redefinicao")
def validar_token_redefinicao(token: str, session: SessionDep):
    _decodificar_token_redefinicao(token, session)
    return {"valido": True}


@router.post("/redefinir-senha")
def redefinir_senha(dados: RedefinirSenhaDTO, session: SessionDep):
    usuario = _decodificar_token_redefinicao(dados.token, session)

    usuario.set_senha(dados.nova_senha)
    session.add(usuario)
    session.commit()

    return {"detail": "Senha redefinida com sucesso."}
