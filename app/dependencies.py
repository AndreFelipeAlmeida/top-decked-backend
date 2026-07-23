from app.core.security import (
    OAUTH2_SCHEME,
    ALGORITHM,
    SECRET_KEY,
    COOKIE_ACCESS_TOKEN,
    COOKIE_CSRF_TOKEN,
    TokenData, validar_token)
from app.core.exception import TopDeckedException
from app.core.db import SessionDep

from typing import Annotated
from fastapi import Depends, Request
from sqlmodel import Session, text
from sqlalchemy import event
import jwt

_METODOS_MUTAVEIS = {"POST", "PUT", "PATCH", "DELETE"}


def _reaplicar_gucs_de_tenant(session: Session, transaction, connection) -> None:
    """Listener global (registrado uma única vez na classe `Session` — vale
    pra toda Session do app inteiro, não só a de uma requisição específica)
    que reaplica as GUCs de tenant a cada nova transação física que essa
    Session abrir. Necessário porque `SET LOCAL` (a variante correta de usar
    aqui — ver definir_tenant_sessao) só vale para UMA transação: uma rota
    que faz `session.commit()` no meio do seu próprio corpo (comum neste
    código — ex.: torneio.py:finalizar_torneio precisa comitar o status do
    torneio antes de chamar recalcular_conquistas_jogador, que faz seu
    próprio commit no fim) abre, implicitamente, uma transação NOVA assim
    que a próxima query roda — e, sem este listener, essa segunda transação
    nasceria sem tenant nenhum declarado, fail-closed pelo resto da
    requisição mesmo já tendo passado pela autorização no início.

    `session.info` é um dict da própria Session (não da transação) — sobrevive
    a qualquer `commit()`/`rollback()` intermediário, e é exatamente por isso
    que serve de fonte de verdade aqui, em vez de reaplicar só uma vez."""
    if connection.dialect.name != "postgresql":
        return
    loja_id = session.info.get("_tenant_loja_id")
    if loja_id is not None:
        connection.execute(text("SET LOCAL app.current_loja_id = :loja_id"), {"loja_id": loja_id})
    if session.info.get("_leitura_publica"):
        connection.execute(text("SET LOCAL app.leitura_publica = 'on'"))


event.listen(Session, "after_begin", _reaplicar_gucs_de_tenant)


def definir_tenant_sessao(session: Session, loja_id: int) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    session.info["_tenant_loja_id"] = loja_id
    session.execute(text("SET LOCAL app.current_loja_id = :loja_id"), {"loja_id": loja_id})


def permitir_leitura_publica(session: SessionDep) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    session.info["_leitura_publica"] = True
    session.execute(text("SET LOCAL app.leitura_publica = 'on'"))


def contexto_dominio(request: Request) -> int | None:
    return getattr(request.state, "loja_id", None)


def _token_data_do_payload(payload: dict) -> TokenData:
    token_data = TokenData(
        id=payload.get("id"),
        tipo=payload.get("tipo"),
        nome=payload.get("nome"),
        email=payload.get("email"),
        usuario_id=payload.get("usuario_id"),
    )
    if token_data.tipo == "loja":
        token_data.endereco = payload.get("endereco")
        token_data.slug = payload.get("slug")
    return token_data


async def retornar_usuario_atual(
    request: Request,
    session: SessionDep,
    token_header: Annotated[str | None, Depends(OAUTH2_SCHEME)] = None,
):
    token_cookie = request.cookies.get(COOKIE_ACCESS_TOKEN)
    token = token_cookie or token_header
    if not token:
        raise TopDeckedException.unauthorized()

    # Só exige CSRF quando o cookie é a ÚNICA prova de identidade da
    # requisição (token_header ausente) — é exatamente o caso que um
    # ataque CSRF de verdade consegue forjar (form/fetch simples cross-site
    # manda cookie automaticamente, mas não consegue setar um header
    # Authorization arbitrário sem passar pelo CORS). Uma requisição que já
    # trouxe um Authorization válido não é CSRF, é um cliente que sabe o
    # token — não tem o que proteger aí.
    if token_cookie and not token_header and request.method in _METODOS_MUTAVEIS:
        csrf_cookie = request.cookies.get(COOKIE_CSRF_TOKEN)
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            raise TopDeckedException.forbidden("Token CSRF ausente ou inválido")

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )
        if not await validar_token(payload=payload, session=session):
            raise TopDeckedException.unauthorized()
    except jwt.ExpiredSignatureError:
        raise TopDeckedException.unauthorized("Token expirado")
    except jwt.InvalidTokenError:
        raise TopDeckedException.unauthorized("Token inválido")

    return _token_data_do_payload(payload)


async def retornar_usuario_atual_opcional(
    request: Request,
    session: SessionDep,
    token_header: Annotated[str | None, Depends(OAUTH2_SCHEME)] = None,
) -> TokenData | None:
    token = request.cookies.get(COOKIE_ACCESS_TOKEN) or token_header
    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not await validar_token(payload=payload, session=session):
            return None
    except jwt.PyJWTError:
        return None

    return _token_data_do_payload(payload)


async def retornar_loja_atual(
    session: SessionDep,
    token_data: Annotated[str, Depends(retornar_usuario_atual)],
):
    if not token_data.tipo == "loja":
        raise TopDeckedException.forbidden()

    # Toda rota que autentica "eu sou esta loja, agindo em nome dela"
    # (criar/editar torneio, gerar rodada, gerenciar estoque, etc.) já sabe
    # o tenant certo aqui — nenhum código de rota precisa lembrar de chamar
    # nada à parte.
    definir_tenant_sessao(session, token_data.id)
    return token_data


async def retornar_jogador_atual(token_data: Annotated[str, Depends(retornar_usuario_atual)]) -> TokenData:
    if not token_data.tipo == "jogador":
        raise TopDeckedException.forbidden()

    return token_data


async def retornar_admin_atual(token_data: Annotated[str, Depends(retornar_usuario_atual)]) -> TokenData:
    if not token_data.tipo == "admin":
        raise TopDeckedException.forbidden()

    return token_data
