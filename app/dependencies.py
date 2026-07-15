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
import jwt

# BRK-309: SameSite=Lax ainda deixa passar GET "top-level navigation"
# cross-site (é o que permite abrir um link e continuar logado), mas
# qualquer mutação (POST/PUT/PATCH/DELETE) feita via cookie precisa do
# token CSRF batendo — GET nunca muda estado, então fica de fora de
# propósito (checar CSRF em GET só quebraria navegação normal sem
# proteger nada).
_METODOS_MUTAVEIS = {"POST", "PUT", "PATCH", "DELETE"}


def contexto_dominio(request: Request) -> int | None:
    """Loja injetada por TenantHostMiddleware a partir do subdomínio da
    requisição (BRK-307) — None em modo global (domínio raiz/sem
    subdomínio). Endpoints que precisam adaptar a resposta ao subdomínio
    (ex.: GET /tenant/atual, BRK-308) importam esta dependency; quem não
    liga pro domínio simplesmente não a usa.

    request.state.loja_id só existe quando o middleware roda de verdade
    (toda requisição HTTP real via ASGI); em testes que chamam a função de
    rota diretamente (fora do app ASGI) ele não estaria setado — getattr
    com default cobre esse caso."""
    return getattr(request.state, "loja_id", None)


async def retornar_usuario_atual(
    request: Request,
    session: SessionDep,
    token_header: Annotated[str | None, Depends(OAUTH2_SCHEME)] = None,
):
    # BRK-309: cookie é a fonte primária (é o que o browser manda sozinho,
    # inclusive entre subdomínios — Domain=.brickei.com.br); o header
    # Authorization vira só o fallback pra clientes que não são browser
    # (scripts, apps mobile) e por isso não têm cookie nenhum.
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

    id = payload.get("id")
    tipo = payload.get("tipo")
    nome = payload.get("nome")
    email = payload.get("email")
    usuario_id = payload.get("usuario_id")

    token_data = TokenData(id=id, tipo=tipo, nome=nome,
                           email=email, usuario_id=usuario_id)

    if tipo == "loja":
        token_data.endereco = payload.get("endereco")
        token_data.slug = payload.get("slug")

    return token_data


async def retornar_loja_atual(token_data: Annotated[str, Depends(retornar_usuario_atual)]):
    if not token_data.tipo == "loja":
        raise TopDeckedException.forbidden()

    return token_data


async def retornar_jogador_atual(token_data: Annotated[str, Depends(retornar_usuario_atual)]) -> TokenData:
    if not token_data.tipo == "jogador":
        raise TopDeckedException.forbidden()

    return token_data


async def retornar_admin_atual(token_data: Annotated[str, Depends(retornar_usuario_atual)]) -> TokenData:
    if not token_data.tipo == "admin":
        raise TopDeckedException.forbidden()

    return token_data
