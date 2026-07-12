from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual, retornar_jogador_atual, retornar_usuario_atual
from app.models import Temporada, LojaJogadorLink, LojaJogadorOrganizadorTCG
from app.schemas.Temporada import TemporadaCriarDTO, TemporadaCriarOrganizadorDTO, TemporadaPublico

router = APIRouter(
    prefix="/lojas/temporadas",
    tags=["Temporadas"])


def _verificar_organizador(session: SessionDep, loja_id: int, jogador_id: int) -> None:
    link = session.exec(
        select(LojaJogadorLink).where(
            (LojaJogadorLink.loja_id == loja_id) & (LojaJogadorLink.jogador_id == jogador_id)
        )
    ).first()

    if not link:
        raise TopDeckedException.forbidden("Jogador não pertence a esta loja")

    organizador = session.exec(
        select(LojaJogadorOrganizadorTCG).where(
            LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id
        )
    ).first()

    if not organizador:
        raise TopDeckedException.forbidden("Jogador não é organizador desta loja")


def _verificar_permissao_temporada(session: SessionDep, temporada: Temporada, usuario: TokenData) -> None:
    """Mesma regra dual usada em TorneioService.verificar_permissao_gerenciar_torneio
    e EventoService.verificar_permissao_evento: autoriza tanto a loja dona da
    temporada quanto um jogador que a organiza."""
    if usuario.tipo == "loja":
        if temporada.loja_id != usuario.id:
            raise TopDeckedException.forbidden()
        return

    if usuario.tipo == "jogador":
        _verificar_organizador(session, temporada.loja_id, usuario.id)
        return

    raise TopDeckedException.forbidden()


@router.post("/", response_model=TemporadaPublico)
def criar_temporada(
    session: SessionDep,
    temporada: TemporadaCriarDTO,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)],
):
    nova_temporada = Temporada(**temporada.model_dump(), loja_id=loja.id)

    session.add(nova_temporada)
    session.commit()
    session.refresh(nova_temporada)
    return nova_temporada


@router.post("/organizador", response_model=TemporadaPublico)
def criar_temporada_organizador(
    session: SessionDep,
    temporada: TemporadaCriarOrganizadorDTO,
    jogador: Annotated[TokenData, Depends(retornar_jogador_atual)],
):
    _verificar_organizador(session, temporada.loja_id, jogador.id)

    dados = temporada.model_dump(exclude={"loja_id"})
    nova_temporada = Temporada(**dados, loja_id=temporada.loja_id)

    session.add(nova_temporada)
    session.commit()
    session.refresh(nova_temporada)
    return nova_temporada


@router.get("/", response_model=list[TemporadaPublico])
def get_temporadas(
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)],
    tcg: str | None = None,
):
    query = select(Temporada).where(Temporada.loja_id == loja.id)
    if tcg:
        query = query.where(Temporada.tcg == tcg)

    return session.exec(query).all()


@router.get("/loja/{loja_id}", response_model=list[TemporadaPublico])
def get_temporadas_loja(
    session: SessionDep,
    loja_id: int,
    jogador: Annotated[TokenData, Depends(retornar_jogador_atual)],
    tcg: str | None = None,
):
    _verificar_organizador(session, loja_id, jogador.id)

    query = select(Temporada).where(Temporada.loja_id == loja_id)
    if tcg:
        query = query.where(Temporada.tcg == tcg)

    return session.exec(query).all()


@router.delete("/{temporada_id}", status_code=204)
def deletar_temporada(
    temporada_id: int,
    session: SessionDep,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    temporada = session.get(Temporada, temporada_id)

    if not temporada:
        raise TopDeckedException.not_found("Temporada não encontrada.")

    _verificar_permissao_temporada(session, temporada, usuario)

    session.delete(temporada)
    session.commit()
