from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.core.db import get_session
from app.models import Item, Loja
from app.dependencies import retornar_loja_atual
from typing import List

router = APIRouter(
    prefix="/lojas/itens",
    tags=["Item"])


@router.post("/", response_model=Item)
def create_item(item: Item, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.get("/", response_model=List[Item])
def read_items(skip: int = 0, limit: int = 100, session: Session = Depends(get_session)):
    items = session.exec(select(Item).offset(skip).limit(limit)).all()
    return items


@router.get("/{item_id}", response_model=Item)
def read_item(item_id: int, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    return item


@router.put("/{item_id}", response_model=Item)
def update_item(item_id: int, item: Item, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    db_item = session.get(Item, item_id)
    if not db_item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    item_data = item.dict(exclude_unset=True)
    for key, value in item_data.items():
        setattr(db_item, key, value)
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item


@router.delete("/{item_id}", response_model=Item)
def delete_item(item_id: int, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    session.delete(item)
    session.commit()
    return item
