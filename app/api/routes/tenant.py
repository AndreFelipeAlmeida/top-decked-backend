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
    if loja_id is None:
        return None

    return session.get(Loja, loja_id)
