from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.core.db import get_session
from app.models import Estoque, Loja, Item
from app.dependencies import retornar_loja_atual
from typing import List

router = APIRouter(
    prefix="/lojas/estoque",
    tags=["Estoque"]
)


@router.post("/", response_model=Estoque)
def create_estoque(estoque: Estoque, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    item = session.get(Item, estoque.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    db_estoque = session.exec(select(Estoque).where(
        Estoque.item_id == estoque.item_id, Estoque.loja_id == current_loja.id)).first()
    if db_estoque:
        raise HTTPException(
            status_code=400, detail="O item já existe no estoque desta loja.")

    estoque.loja_id = current_loja.id
    session.add(estoque)
    session.commit()
    session.refresh(estoque)
    return estoque


@router.get("/", response_model=List[Estoque])
def read_estoques(skip: int = 0, limit: int = 100, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    estoques = session.exec(select(Estoque).where(
        Estoque.loja_id == current_loja.id).offset(skip).limit(limit)).all()
    return estoques


@router.get("/{item_id}", response_model=Estoque)
def read_estoque(item_id: int, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    estoque = session.exec(select(Estoque).where(
        Estoque.item_id == item_id, Estoque.loja_id == current_loja.id)).first()
    if not estoque:
        raise HTTPException(status_code=404, detail="Estoque não encontrado.")
    return estoque


@router.put("/{item_id}", response_model=Estoque)
def update_estoque(item_id: int, estoque: Estoque, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    db_estoque = session.exec(select(Estoque).where(
        Estoque.item_id == item_id, Estoque.loja_id == current_loja.id)).first()
    if not db_estoque:
        raise HTTPException(status_code=404, detail="Estoque não encontrado.")

    estoque_data = estoque.dict(exclude_unset=True)
    for key, value in estoque_data.items():
        setattr(db_estoque, key, value)

    session.add(db_estoque)
    session.commit()
    session.refresh(db_estoque)
    return db_estoque


@router.delete("/{item_id}", response_model=Estoque)
def delete_estoque(item_id: int, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    estoque = session.exec(select(Estoque).where(
        Estoque.item_id == item_id, Estoque.loja_id == current_loja.id)).first()
    if not estoque:
        raise HTTPException(status_code=404, detail="Estoque não encontrado.")
    session.delete(estoque)
    session.commit()
    return estoque
