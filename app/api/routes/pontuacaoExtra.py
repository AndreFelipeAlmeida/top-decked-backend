from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual, retornar_jogador_atual
from app.models import LojaJogadorLink, LojaJogadorOrganizadorTCG, PontuacaoExtra, Torneio
from app.schemas.PontuacaoExtra import PontuacaoExtraPublico
from app.services.PontuacaoExtraService import retornar_pontuacao_extra_completa

router = APIRouter(
    prefix="/lojas/pontuacao-extra",
    tags=["Pontuação Extra"])


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


@router.get("/", response_model=list[PontuacaoExtraPublico])
def get_historico_pontuacao_extra(
    session: SessionDep,
    loja: Annotated[TokenData, Depends(retornar_loja_atual)],
    tcg: str | None = None,
):
    query = select(PontuacaoExtra).join(Torneio).where(Torneio.loja_id == loja.id)
    if tcg:
        query = query.where(Torneio.jogo == tcg)
    query = query.order_by(PontuacaoExtra.criado_em.desc())

    resultados = session.exec(query).all()
    return [retornar_pontuacao_extra_completa(pe) for pe in resultados]


@router.get("/organizador", response_model=list[PontuacaoExtraPublico])
def get_historico_pontuacao_extra_organizador(
    session: SessionDep,
    loja_id: int,
    jogador: Annotated[TokenData, Depends(retornar_jogador_atual)],
    tcg: str | None = None,
):
    _verificar_organizador(session, loja_id, jogador.id)

    query = select(PontuacaoExtra).join(Torneio).where(Torneio.loja_id == loja_id)
    if tcg:
        query = query.where(Torneio.jogo == tcg)
    query = query.order_by(PontuacaoExtra.criado_em.desc())

    resultados = session.exec(query).all()
    return [retornar_pontuacao_extra_completa(pe) for pe in resultados]
