from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.dependencies import retornar_admin_atual
from app.models import Loja
from app.schemas.Loja import LojaPublico
from app.services.AdminEntidadeService import (
    atualizar_registro,
    criar_registro,
    deletar_registro,
    descrever_colunas,
    listar_entidades,
    listar_registros,
)
from app.utils.Enums import StatusAprovacaoLoja
from sqlmodel import select

router = APIRouter(prefix="/admin", tags=["Admin"])


# ---------------------------------- Moderação de Lojas ----------------------------------

@router.get("/lojas/pendentes", response_model=list[LojaPublico])
def listar_lojas_pendentes(session: SessionDep, _: Annotated[TokenData, Depends(retornar_admin_atual)]):
    return session.exec(select(Loja).where(Loja.status == StatusAprovacaoLoja.PENDENTE)).all()


@router.put("/lojas/{loja_id}/aprovar", response_model=LojaPublico)
def aprovar_loja(loja_id: int, session: SessionDep, _: Annotated[TokenData, Depends(retornar_admin_atual)]):
    loja = session.get(Loja, loja_id)
    if not loja:
        raise TopDeckedException.not_found("Loja não encontrada")

    loja.status = StatusAprovacaoLoja.APROVADA
    session.add(loja)
    session.commit()
    session.refresh(loja)
    return loja


@router.put("/lojas/{loja_id}/rejeitar", response_model=LojaPublico)
def rejeitar_loja(loja_id: int, session: SessionDep, _: Annotated[TokenData, Depends(retornar_admin_atual)]):
    loja = session.get(Loja, loja_id)
    if not loja:
        raise TopDeckedException.not_found("Loja não encontrada")

    loja.status = StatusAprovacaoLoja.REJEITADA
    session.add(loja)
    session.commit()
    session.refresh(loja)
    return loja


# ---------------------------------- CRUD Dinâmico de Entidades ----------------------------------

@router.get("/entidades")
def get_entidades(_: Annotated[TokenData, Depends(retornar_admin_atual)]):
    return listar_entidades()


@router.get("/entidades/{nome}/colunas")
def get_colunas_entidade(nome: str, _: Annotated[TokenData, Depends(retornar_admin_atual)]):
    return descrever_colunas(nome)


@router.get("/entidades/{nome}")
def get_registros_entidade(nome: str, session: SessionDep, _: Annotated[TokenData, Depends(retornar_admin_atual)]):
    return listar_registros(session, nome)


@router.post("/entidades/{nome}")
def post_registro_entidade(
    nome: str,
    dados: dict[str, Any],
    session: SessionDep,
    _: Annotated[TokenData, Depends(retornar_admin_atual)],
):
    return criar_registro(session, nome, dados)


@router.put("/entidades/{nome}/{registro_id}")
def put_registro_entidade(
    nome: str,
    registro_id: str,
    dados: dict[str, Any],
    session: SessionDep,
    _: Annotated[TokenData, Depends(retornar_admin_atual)],
):
    return atualizar_registro(session, nome, registro_id, dados)


@router.delete("/entidades/{nome}/{registro_id}", status_code=204)
def delete_registro_entidade(
    nome: str,
    registro_id: str,
    session: SessionDep,
    _: Annotated[TokenData, Depends(retornar_admin_atual)],
):
    deletar_registro(session, nome, registro_id)
