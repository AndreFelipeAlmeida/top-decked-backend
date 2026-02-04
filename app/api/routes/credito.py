from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from app.core.db import SessionDep
from app.models import Credito, Loja
from typing import List, Annotated
from app.dependencies import retornar_loja_atual
from app.core.security import TokenData
from app.schemas.Credito import CreditoCreate, CreditoUpdate, CreditoAdd

router = APIRouter(
    prefix="/creditos",
    tags=["Creditos"]
)


@router.post("/", response_model=Credito)
def create_credito(credito_create: CreditoCreate, session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    credito = Credito(jogador_id=credito_create.jogador_id,
                      loja_id=loja.id, quantidade=credito_create.quantidade)
    session.add(credito)
    session.commit()
    session.refresh(credito)
    return credito


@router.get("/", response_model=List[Credito])
def get_creditos_by_loja(session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    creditos = session.exec(select(Credito).where(
        Credito.loja_id == loja.id)).all()
    return creditos


@router.patch("/{jogador_id}/adicionar-credito", response_model=Credito)
def add_credito(jogador_id: int, data: CreditoAdd, session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    credito = session.get(Credito, (jogador_id, loja.id))
    if not credito:
        credito = Credito(jogador_id=jogador_id,
                          loja_id=loja.id)

    credito.quantidade += data.novos_creditos
    session.add(credito)
    session.commit()
    session.refresh(credito)
    return credito


@router.put("/{jogador_id}", response_model=Credito)
def update_credito(jogador_id: int, credito_update: CreditoUpdate, session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    credito = session.get(Credito, (jogador_id, loja.id))
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito não encontrado")
    credito.quantidade = credito_update.quantidade
    session.add(credito)
    session.commit()
    session.refresh(credito)
    return credito


@router.delete("/{jogador_id}", status_code=204)
def delete_credito(jogador_id: int, session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    credito = session.get(Credito, (jogador_id, loja.id))
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito não encontrado")
    session.delete(credito)
    session.commit()
    return None
