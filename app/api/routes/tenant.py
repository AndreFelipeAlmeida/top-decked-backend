from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.db import SessionDep
from app.dependencies import contexto_dominio
from app.models import Loja
from app.schemas.Loja import LojaPublico

router = APIRouter(prefix="/tenant", tags=["Tenant"])


@router.get("/atual")
def get_tenant_atual(
    session: SessionDep,
    loja_id: Annotated[int | None, Depends(contexto_dominio)],
) -> LojaPublico | None:
    """Endpoint público leve (BRK-308): o frontend chama isso no boot da
    SPA pra saber se está rodando no domínio raiz (retorna None — modo
    global) ou num subdomínio de loja (retorna os dados públicos dessa
    loja, já resolvidos pelo TenantHostMiddleware a partir do Host). Fonte
    única de verdade da extração de slug é o backend — o frontend nunca
    duplica essa lógica via regex."""
    if loja_id is None:
        return None

    return session.get(Loja, loja_id)
