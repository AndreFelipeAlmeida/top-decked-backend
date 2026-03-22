from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.models import LojaJogadorLink, Loja, GameID, Jogador
from typing import List, Annotated
from app.dependencies import retornar_loja_atual, retornar_jogador_atual
from app.core.security import TokenData
from app.schemas.LojaJogadorLink import CreditoCreate, CreditoUpdate, CreditoAdd, CreditoJogador, CreditoRemove

router = APIRouter(
    prefix="/creditos",
    tags=["Creditos"]
)


@router.post("/", response_model=LojaJogadorLink)
def create_credito(credito_create: CreditoCreate, session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    jogador = session.exec(select(Jogador)
                 .join(GameID, GameID.jogador_id == Jogador.id)
                 .where((GameID.tcg == credito_create.game_id.tcg) &
                        (GameID.jogador_id == credito_create.game_id.id))).first()
                 

    query = select(LojaJogadorLink).where(
        LojaJogadorLink.loja_id == loja.id
    )

    if jogador:
        query = query.where(
            LojaJogadorLink.jogador_id == jogador.id
        )
    else:
        query = query.where(
            LojaJogadorLink.game_id == credito_create.game_id.id
        )

    credito_existente = session.exec(query).first()
    
    if credito_existente:
        raise TopDeckedException.bad_request("Jogador já cadastrado")
    
    credito = LojaJogadorLink(jogador_id=jogador.id if jogador else None,
                            game_id=credito_create.game_id.id,
                            tcg=credito_create.game_id.tcg,
                            apelido=credito_create.apelido,
                            loja_id=loja.id, quantidade=0)
    
    session.add(credito)
    session.commit()
    session.refresh(credito)
    return credito


@router.get("/jogador", response_model=List[CreditoJogador])
def get_creditos_by_jogador(session: SessionDep, jogador: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    creditos = session.exec(select(LojaJogadorLink, Loja)
                            .join(Loja, Loja.id == LojaJogadorLink.loja_id)
                            .where(LojaJogadorLink.jogador_id == jogador.id)).all()

    creditos_formatados = []

    for credito, loja in creditos:
        credito_data = credito.model_dump()
        credito_data["nome_loja"] = loja.nome
        credito_data["endereco"] = loja.endereco
        creditos_formatados.append(credito_data)

    return creditos_formatados


@router.get("/", response_model=List[LojaJogadorLink])
def get_creditos_by_loja(session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    creditos = session.exec(select(LojaJogadorLink).where(
        LojaJogadorLink.loja_id == loja.id)).all()
    return creditos


@router.patch("/{jogador_id}/adicionar-credito", response_model=LojaJogadorLink)
def add_credito(jogador_id: int, data: CreditoAdd, session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    credito = session.get(LojaJogadorLink, (jogador_id, loja.id))
    if not credito:
        credito = LojaJogadorLink(jogador_id=jogador_id,
                                  loja_id=loja.id)

    credito.quantidade += data.novos_creditos
    session.add(credito)
    session.commit()
    session.refresh(credito)
    return credito


@router.patch("/{jogador_id}/remover-credito", response_model=LojaJogadorLink)
def remover_credito(jogador_id: int, data: CreditoRemove, session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    credito = session.get(LojaJogadorLink, (jogador_id, loja.id))
    if credito:
        credito.quantidade = max(0, credito.quantidade - data.retirar_creditos)
        session.add(credito)
        session.commit()
        session.refresh(credito)

    return credito


@router.put("/{jogador_id}", response_model=LojaJogadorLink)
def update_credito(jogador_id: int, credito_update: CreditoUpdate, session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    credito = session.get(LojaJogadorLink, (jogador_id, loja.id))
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito não encontrado")
    credito.quantidade = credito_update.quantidade
    session.add(credito)
    session.commit()
    session.refresh(credito)
    return credito


@router.delete("/{jogador_id}", status_code=204)
def delete_credito(credito_id: int, session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    credito = session.get(LojaJogadorLink, credito_id)
    
    if not credito:
        raise HTTPException(status_code=404, detail="Crédito não encontrado")
    session.delete(credito)
    session.commit()
    return None
