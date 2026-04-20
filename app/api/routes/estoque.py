from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.core.db import get_session, SessionDep
from app.models import Item, Loja, HistoricoItem, ItemBase
from app.dependencies import retornar_loja_atual
from app.utils.Enums import TipoMovimentacaoItem
from app.schemas.Estoque import MovimentacaoItem


router = APIRouter(
    prefix="/lojas/item",
    tags=["Item"]
)


@router.post("/", response_model=Item)
def create_item(session: SessionDep, item: Item, current_loja: Loja = Depends(retornar_loja_atual)):
    db_item = session.exec(select(Item).where(
        Item.id == item.id, Item.loja_id == current_loja.id)).first()
    if db_item:
        raise HTTPException(
            status_code=400, detail="O item já existe no item desta loja.")

    item.loja_id = current_loja.id
    session.add(item)
    session.commit()
    session.refresh(item)

    historico = HistoricoItem(item_id=item.id,
                              nome_item=item.nome,
                              loja_id=current_loja.id,
                              quantidade=item.quantidade,
                              tipo=TipoMovimentacaoItem.CADASTRO)

    session.add(historico)
    session.commit()

    return item


@router.get("/", response_model=List[Item])
def read_items(session: SessionDep, skip: int = 0, limit: int = 100, current_loja: Loja = Depends(retornar_loja_atual)):
    items = session.exec(select(Item).where(
        Item.loja_id == current_loja.id).offset(skip).limit(limit)).all()
    return items


@router.get("/{item_id}", response_model=Item)
def read_item(id: int, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    item = session.exec(select(Item).where(
        Item.id == id, Item.loja_id == current_loja.id)).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    return item


@router.put("/{id}", response_model=Item)
def update_item(
    session: SessionDep,
    id: int,
    item: ItemBase,
    current_loja: Loja = Depends(retornar_loja_atual),
):
    db_item = session.exec(select(Item).where(
        Item.id == id,
        Item.loja_id == current_loja.id
    )).first()

    if not db_item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    item_data = item.model_dump(exclude_unset=True)

    campos_monitorados = ["nome", "preco", "categoria", "min_quantidade"]

    for campo in campos_monitorados:
        if campo in item_data:
            valor_antigo = getattr(db_item, campo)
            valor_novo = item_data[campo]

            if valor_antigo != valor_novo:
                historico = HistoricoItem(
                    item_id=db_item.id,
                    loja_id=current_loja.id,
                    nome_item=db_item.nome,
                    tipo=TipoMovimentacaoItem.ALTERACAO,
                    campo_alterado=campo,
                    valor_antigo=str(valor_antigo),
                    valor_novo=str(valor_novo),
                    descricao=f"{campo} alterado"
                )
                session.add(historico)

    for key, value in item_data.items():
        setattr(db_item, key, value)

    session.add(db_item)
    session.commit()
    session.refresh(db_item)

    return db_item


@router.post("/{id}/movimentar", response_model=Item)
def movimentar_item(
    session: SessionDep,
    id: int,
    data: MovimentacaoItem,
    current_loja: Loja = Depends(retornar_loja_atual),
):
    db_item = session.exec(select(Item).where(
        Item.id == id,
        Item.loja_id == current_loja.id
    )).first()

    if not db_item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    if data.quantidade <= 0:
        raise HTTPException(
            status_code=400, detail="Quantidade deve ser maior que zero.")

    if data.tipo == TipoMovimentacaoItem.ENTRADA:
        db_item.quantidade += data.quantidade

    elif data.tipo == TipoMovimentacaoItem.SAIDA:
        if db_item.quantidade < data.quantidade:
            raise HTTPException(
                status_code=400, detail="Item insuficiente.")
        db_item.quantidade -= data.quantidade

    historico = HistoricoItem(
        item_id=db_item.id,
        loja_id=current_loja.id,
        nome_item=db_item.nome,
        quantidade=data.quantidade,
        tipo=data.tipo,
        descricao=data.descricao or "Movimentação manual"
    )

    session.add(historico)
    session.add(db_item)

    session.commit()
    session.refresh(db_item)

    return db_item


@router.delete("/{id}", response_model=Item)
def delete_item(
    session: SessionDep,
    id: int,
    current_loja: Loja = Depends(retornar_loja_atual)
):
    item = session.exec(select(Item).where(
        Item.id == id,
        Item.loja_id == current_loja.id
    )).first()

    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    historico = HistoricoItem(
        loja_id=current_loja.id,
        tipo=TipoMovimentacaoItem.REMOCAO,
        descricao=f"Item '{item.nome}' removido do item"
    )

    session.add(historico)
    session.delete(item)
    session.commit()

    return item
