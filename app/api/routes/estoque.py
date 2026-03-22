from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.core.db import get_session, SessionDep
from app.models import Estoque, Loja, HistoricoEstoque, EstoqueBase
from app.dependencies import retornar_loja_atual
from app.utils.Enums import TipoMovimentacaoEstoque
from app.schemas.Estoque import MovimentacaoEstoque


router = APIRouter(
    prefix="/lojas/estoque",
    tags=["Estoque"]
)

@router.post("/", response_model=Estoque)
def create_estoque(session: SessionDep, estoque: Estoque, current_loja: Loja = Depends(retornar_loja_atual)):
    db_estoque = session.exec(select(Estoque).where(
        Estoque.id == estoque.id, Estoque.loja_id == current_loja.id)).first()
    if db_estoque:
        raise HTTPException(
            status_code=400, detail="O item já existe no estoque desta loja.")

    estoque.loja_id = current_loja.id
    session.add(estoque)
    session.commit()
    session.refresh(estoque)
    
    historico = HistoricoEstoque(estoque_id=estoque.id, 
                                nome_item=estoque.nome, 
                                loja_id=current_loja.id, 
                                quantidade=estoque.quantidade,
                                tipo=TipoMovimentacaoEstoque.CADASTRO)
     
    session.add(historico)
    session.commit()
    
    return estoque


@router.get("/", response_model=List[Estoque])
def read_estoques(session: SessionDep, skip: int = 0, limit: int = 100, current_loja: Loja = Depends(retornar_loja_atual)):
    estoques = session.exec(select(Estoque).where(
        Estoque.loja_id == current_loja.id).offset(skip).limit(limit)).all()
    return estoques


@router.get("/{item_id}", response_model=Estoque)
def read_estoque(id: int, current_loja: Loja = Depends(retornar_loja_atual), session: Session = Depends(get_session)):
    estoque = session.exec(select(Estoque).where(
        Estoque.id == id, Estoque.loja_id == current_loja.id)).first()
    if not estoque:
        raise HTTPException(status_code=404, detail="Estoque não encontrado.")
    return estoque


@router.put("/{id}", response_model=Estoque)
def update_estoque(
    session: SessionDep,
    id: int,
    estoque: EstoqueBase,
    current_loja: Loja = Depends(retornar_loja_atual),
):
    db_estoque = session.exec(select(Estoque).where(
        Estoque.id == id,
        Estoque.loja_id == current_loja.id
    )).first()

    if not db_estoque:
        raise HTTPException(status_code=404, detail="Estoque não encontrado.")

    estoque_data = estoque.model_dump(exclude_unset=True)

    campos_monitorados = ["nome", "preco", "categoria", "min_quantidade"]

    for campo in campos_monitorados:
        if campo in estoque_data:
            valor_antigo = getattr(db_estoque, campo)
            valor_novo = estoque_data[campo]

            if valor_antigo != valor_novo:
                historico = HistoricoEstoque(
                    estoque_id=db_estoque.id,
                    loja_id=current_loja.id,
                    nome_item=db_estoque.nome,
                    tipo=TipoMovimentacaoEstoque.ALTERACAO,
                    campo_alterado=campo,
                    valor_antigo=str(valor_antigo),
                    valor_novo=str(valor_novo),
                    descricao=f"{campo} alterado"
                )
                session.add(historico)

    for key, value in estoque_data.items():
        setattr(db_estoque, key, value)

    session.add(db_estoque)
    session.commit()
    session.refresh(db_estoque)

    return db_estoque


@router.post("/{id}/movimentar", response_model=Estoque)
def movimentar_estoque(
    session: SessionDep,
    id: int,
    data: MovimentacaoEstoque,
    current_loja: Loja = Depends(retornar_loja_atual),
):
    db_estoque = session.exec(select(Estoque).where(
        Estoque.id == id,
        Estoque.loja_id == current_loja.id
    )).first()

    if not db_estoque:
        raise HTTPException(status_code=404, detail="Estoque não encontrado.")

    if data.quantidade <= 0:
        raise HTTPException(
            status_code=400, detail="Quantidade deve ser maior que zero.")

    if data.tipo == TipoMovimentacaoEstoque.ENTRADA:
        db_estoque.quantidade += data.quantidade

    elif data.tipo == TipoMovimentacaoEstoque.SAIDA:
        if db_estoque.quantidade < data.quantidade:
            raise HTTPException(
                status_code=400, detail="Estoque insuficiente.")
        db_estoque.quantidade -= data.quantidade

    historico = HistoricoEstoque(
        estoque_id=db_estoque.id,
        loja_id=current_loja.id,
        nome_item=db_estoque.nome,
        quantidade=data.quantidade,
        tipo=data.tipo,
        descricao=data.descricao or "Movimentação manual"
    )

    session.add(historico)
    session.add(db_estoque)

    session.commit()
    session.refresh(db_estoque)

    return db_estoque


@router.delete("/{id}", response_model=Estoque)
def delete_estoque(
    session: SessionDep,
    id: int,
    current_loja: Loja = Depends(retornar_loja_atual)
):
    estoque = session.exec(select(Estoque).where(
        Estoque.id == id,
        Estoque.loja_id == current_loja.id
    )).first()

    if not estoque:
        raise HTTPException(status_code=404, detail="Estoque não encontrado.")

    historico = HistoricoEstoque(
        loja_id=current_loja.id,
        tipo=TipoMovimentacaoEstoque.REMOCAO,
        descricao=f"Item '{estoque.nome}' removido do estoque"
    )

    session.add(historico)
    session.delete(estoque)
    session.commit()

    return estoque
