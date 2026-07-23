from app.core.db import SessionDep
from fastapi import APIRouter, Depends
from app.core.exception import TopDeckedException
from typing import Annotated
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual, retornar_jogador_atual
from app.schemas.TipoJogador import TipoJogadorPublico, TipoJogadorAtualizar, TipoJogadorCriarOrganizadorDTO
from app.models import TipoJogador, TipoJogadorBase, LojaJogadorLink, LojaJogadorOrganizadorTCG
from sqlmodel import select


router = APIRouter(
    prefix="/lojas/tipoJogador",
    tags=["Tipo de Jogador"])

@router.post("/", response_model=TipoJogadorPublico)
def criar_tipo_jogador(session: SessionDep, tipo_jogador: TipoJogadorBase, 
                       loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    
    novo_tipo_jogador = TipoJogador(
        **tipo_jogador.model_dump(),
        loja_id=loja.id
    )
    
    session.add(novo_tipo_jogador)
    session.commit()
    session.refresh(novo_tipo_jogador)
    return novo_tipo_jogador

@router.post("/organizador", response_model=TipoJogadorPublico)
def criar_tipo_jogador_organizador(
    session: SessionDep,
    tipo_jogador: TipoJogadorCriarOrganizadorDTO,
    jogador: Annotated[
        TokenData,
        Depends(retornar_jogador_atual)
    ]
):
    link = session.exec(
        select(LojaJogadorLink)
        .where(
            (LojaJogadorLink.loja_id == tipo_jogador.loja_id) &
            (LojaJogadorLink.jogador_id == jogador.id)
        )
    ).first()

    if not link:
        raise TopDeckedException.forbidden(
            "Jogador não pertence a esta loja"
        )

    organizador = session.exec(
        select(LojaJogadorOrganizadorTCG)
        .where(
            LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id
        )
    ).first()

    if not organizador:
        raise TopDeckedException.forbidden(
            "Jogador não é organizador desta loja"
        )

    dados = tipo_jogador.model_dump(exclude={"loja_id"})

    novo_tipo_jogador = TipoJogador(
        **dados,
        loja_id=tipo_jogador.loja_id
    )

    session.add(novo_tipo_jogador)
    session.commit()
    session.refresh(novo_tipo_jogador)
    return novo_tipo_jogador

@router.get("/", response_model=list[TipoJogadorPublico])
def get_tipos_jogador(session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    tipos = session.exec(select(TipoJogador).where(
        TipoJogador.loja_id == loja.id
    )).all()

    return tipos


@router.get(
    "/loja/{loja_id}",
    response_model=list[TipoJogadorPublico]
)
def get_tipos_jogador_loja(
    session: SessionDep,
    loja_id: int,
    jogador: Annotated[
        TokenData,
        Depends(retornar_jogador_atual)
    ]
):
    link = session.exec(
        select(LojaJogadorLink)
        .where(
            (LojaJogadorLink.loja_id == loja_id) &
            (LojaJogadorLink.jogador_id == jogador.id)
        )
    ).first()

    if not link:
        raise TopDeckedException.forbidden(
            "Jogador não pertence a esta loja"
        )

    organizador = session.exec(
        select(LojaJogadorOrganizadorTCG)
        .where(
            LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id
        )
    ).first()

    if not organizador:
        raise TopDeckedException.forbidden(
            "Jogador não é organizador desta loja"
        )

    tipos = session.exec(
        select(TipoJogador)
        .where(
            TipoJogador.loja_id == loja_id
        )
    ).all()

    if not tipos:
        raise TopDeckedException.not_found(
            "Nenhum tipo de jogador encontrado."
        )

    return tipos

@router.get("/{tipo_id}", response_model=TipoJogadorPublico)
def get_tipo_jogador_por_id(
    tipo_id: int,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    tipo = session.exec(select(TipoJogador).where(
        TipoJogador.id == tipo_id,
        TipoJogador.loja_id == loja.id
    )).first()

    if not tipo:
        raise TopDeckedException.not_found("Tipo de jogador não encontrado.")

    return tipo

@router.delete("/{tipo_id}", status_code=204)
def delete_tipo_jogador(
    tipo_id: int,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    tipo = session.exec(select(TipoJogador).where(
        TipoJogador.id == tipo_id,
        TipoJogador.loja_id == loja.id
    )).first()

    if not tipo:
        raise TopDeckedException.not_found("Tipo de jogador não encontrado.")

    session.delete(tipo)
    session.commit()

@router.put("/{tipo_id}", response_model=TipoJogadorPublico)
def atualizar_tipo_jogador(tipo_id: int,
    novo : TipoJogadorAtualizar,
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)]
):
    tipo = session.exec(select(TipoJogador).where(
        TipoJogador.id == tipo_id,
        TipoJogador.loja_id == loja.id
    )).first()

    if not tipo:
        raise TopDeckedException.not_found("Tipo Jogador não encontrado")

    novo_tipo_data = novo.model_dump(exclude_unset=True)

    tipo.sqlmodel_update(novo_tipo_data)
    session.add(tipo)
    session.commit()
    session.refresh(tipo)
    return tipo
