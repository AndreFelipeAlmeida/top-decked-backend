from app.schemas.Categoria import CategoriaCriar
from app.models import Categoria, Item
from app.dependencies import retornar_loja_atual
from app.core.security import TokenData
from app.core.exception import TopDeckedException
from app.core.db import SessionDep
from sqlmodel import select
from fastapi import APIRouter, Depends
from typing import Annotated
from fastapi import APIRouter

router = APIRouter(prefix="/estoque/categoria", tags=["categoria"])


@router.post("/", response_model=Categoria)
def criar_categoria(
    session: SessionDep,
    categoria: CategoriaCriar,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    nova_categoria = Categoria(
        **categoria.model_dump(),
        loja_id=loja.id
    )

    session.add(nova_categoria)
    session.commit()
    session.refresh(nova_categoria)

    return nova_categoria


@router.get("/", response_model=list[Categoria])
def listar_categorias(
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    categorias = session.exec(
        select(Categoria).where(Categoria.loja_id == loja.id)
    ).all()

    if not categorias:
        raise TopDeckedException.not_found(
            "Nenhuma categoria encontrada."
        )

    return categorias


@router.get("/{categoria_id}", response_model=Categoria)
def buscar_categoria_por_id(
    categoria_id: int,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    categoria = session.exec(
        select(Categoria).where(
            Categoria.id == categoria_id,
            Categoria.loja_id == loja.id
        )
    ).first()

    if not categoria:
        raise TopDeckedException.not_found(
            "Categoria não encontrada."
        )

    return categoria


@router.put("/{categoria_id}", response_model=Categoria)
def atualizar_categoria(
    categoria_id: int,
    dados: CategoriaCriar,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    categoria = session.exec(
        select(Categoria).where(
            Categoria.id == categoria_id,
            Categoria.loja_id == loja.id
        )
    ).first()

    if not categoria:
        raise TopDeckedException.not_found(
            "Categoria não encontrada."
        )

    categoria_data = dados.model_dump(exclude_unset=True)

    categoria.sqlmodel_update(categoria_data)
    session.add(categoria)
    session.commit()
    session.refresh(categoria)

    return categoria


@router.delete("/{categoria_id}", status_code=204)
def deletar_categoria(
    categoria_id: int,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    categoria = session.exec(
        select(Categoria).where(
            Categoria.id == categoria_id,
            Categoria.loja_id == loja.id
        )
    ).first()

    if not categoria:
        raise TopDeckedException.not_found(
            "Categoria não encontrada."
        )

    itens = session.exec(select(Item).where(Item.categoria == categoria.id, 
                                            Item.loja_id == loja.id)).all()
    
    if itens:
      raise TopDeckedException.bad_request("Existem itens cadastrados nessa categoria")
    
    session.delete(categoria)
    session.commit()
