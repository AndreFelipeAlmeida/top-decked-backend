from typing import List, Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.models import LojaJogadorLink, Loja, GameID, Jogador, HistoricoCredito
from app.utils.Enums import TipoMovimentacaoCredito
from app.dependencies import retornar_loja_atual, retornar_jogador_atual
from app.core.security import TokenData
from app.schemas.LojaJogadorLink import CreditoCreate, CreditoAdd, CreditoJogador, CreditoRemove, LojaJogadorPublico

router = APIRouter(
    prefix="/creditos",
    tags=["Creditos"]
)


@router.post("/{jogador_id}", response_model=LojaJogadorLink)
def create_credito_by_id(
    jogador_id: int,
    apelido: str,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    jogador = session.get(Jogador, jogador_id)

    if not jogador:
        raise TopDeckedException.not_found("Jogador não encontrado")

    credito = session.exec(select(LojaJogadorLink).where((LojaJogadorLink.loja_id == loja.id) &
                                                         (LojaJogadorLink.jogador_id == jogador_id))).first()

    if credito:
        raise TopDeckedException.bad_request("Vínculo já existente")

    novo_credito = LojaJogadorLink(
        jogador_id=jogador_id, loja_id=loja.id, apelido=apelido, creditos=0)

    historico = HistoricoCredito(
        jogador_id=jogador_id,
        loja_id=loja.id,
        tipo=TipoMovimentacaoCredito.CADASTRO,
        descricao="Ligação entre jogador e loja cadastrada"
    )

    session.add(historico)
    session.add(novo_credito)
    session.commit()
    session.refresh(novo_credito)

    return novo_credito


@router.post("/", response_model=LojaJogadorPublico)
def create_credito(
    credito_create: CreditoCreate,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    jogador = session.exec(
        select(Jogador)
        .join(GameID, GameID.jogador_id == Jogador.id)
        .where(
            (GameID.tcg == credito_create.game_id.tcg) &
            (GameID.jogador_id == credito_create.game_id.id)
        )
    ).first()

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

    credito = LojaJogadorLink(
        jogador_id=jogador.id if jogador else None,
        game_id=credito_create.game_id.id,
        tcg=credito_create.game_id.tcg,
        apelido=credito_create.apelido,
        loja_id=loja.id,
        creditos=0
    )

    session.add(credito)
    session.flush()

    historico = HistoricoCredito(
        jogador_id=credito.jogador_id,
        loja_id=loja.id,
        tipo=TipoMovimentacaoCredito.CADASTRO,
        descricao="Ligação entre jogador e loja cadastrada"
    )
    session.add(historico)

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


@router.get("/", response_model=List[LojaJogadorPublico])
def get_creditos_by_loja(
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)],
    search: str | None = None,
):
    query = (
        select(LojaJogadorLink)
        .options(selectinload(LojaJogadorLink.jogador))
        .where(LojaJogadorLink.loja_id == loja.id)
    )

    if search:
        query = query.where(
            or_(
                LojaJogadorLink.game_id.ilike(f"%{search}%"),
                LojaJogadorLink.apelido.ilike(f"%{search}%"),
                LojaJogadorLink.jogador.has(
                    Jogador.nome.ilike(f"%{search}%")
                ),
            )
        )

    creditos = session.exec(query).all()

    return creditos


@router.patch("/{credito_id}/adicionar-credito", response_model=LojaJogadorLink)
def add_credito(
    credito_id: int,
    data: CreditoAdd,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    if data.novos_creditos <= 0:
        raise HTTPException(
            status_code=400, detail="Valor deve ser maior que zero.")

    credito = session.get(LojaJogadorLink, credito_id)

    if not credito:
        raise HTTPException(status_code=404, detail="Crédito não encontrado.")

    valor_antigo = credito.creditos
    valor_novo = valor_antigo + data.novos_creditos

    credito.creditos = valor_novo

    historico = HistoricoCredito(
        jogador_id=credito.jogador_id,
        loja_id=loja.id,
        valor_antigo=valor_antigo,
        valor_novo=valor_novo,
        tipo=TipoMovimentacaoCredito.ADICAO,
        descricao=f"Adicionado {data.novos_creditos} créditos"
    )

    session.add(historico)
    session.add(credito)

    session.commit()
    session.refresh(credito)

    return credito


@router.patch("/{credito_id}/remover-credito", response_model=LojaJogadorLink)
def remover_credito(
    credito_id: int,
    data: CreditoRemove,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    if data.retirar_creditos <= 0:
        raise HTTPException(
            status_code=400, detail="Valor deve ser maior que zero.")

    credito = session.get(LojaJogadorLink, credito_id)

    if not credito:
        raise HTTPException(status_code=404, detail="Crédito não encontrado.")

    valor_antigo = credito.creditos

    if valor_antigo < data.retirar_creditos:
        raise HTTPException(status_code=400, detail="Saldo insuficiente.")

    valor_novo = valor_antigo - data.retirar_creditos
    credito.creditos = valor_novo

    historico = HistoricoCredito(
        jogador_id=credito.jogador_id,
        loja_id=loja.id,
        valor_antigo=valor_antigo,
        valor_novo=valor_novo,
        tipo=TipoMovimentacaoCredito.REMOCAO,
        descricao=f"Removido {data.retirar_creditos} créditos"
    )

    session.add(historico)
    session.add(credito)

    session.commit()
    session.refresh(credito)

    return credito


@router.delete("/{jogador_id}", response_model=LojaJogadorLink)
def deletar_credito(
    jogador_id: int,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)],
):
    credito = session.exec(
        select(LojaJogadorLink).where(
            (LojaJogadorLink.jogador_id == jogador_id)
            & (LojaJogadorLink.loja_id == loja.id)
        )
    ).first()

    if not credito:
        raise TopDeckedException.not_found("Vínculo não encontrado")

    historico = HistoricoCredito(
        jogador_id=jogador_id,
        loja_id=loja.id,
        tipo=TipoMovimentacaoCredito.REMOCAO,
        descricao="Vínculo entre jogador e loja removido",
    )

    session.delete(credito)
    session.add(historico)
    session.commit()

    return credito
