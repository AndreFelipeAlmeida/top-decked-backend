from fastapi import APIRouter, Query, Depends
from app.core.db import SessionDep
from app.schemas.Ranking import Ranking, RankingPorLoja, RankingPorFormato
from app.services.RankingService import calcula_ranking_geral, calcula_ranking_geral_por_loja, desempenho_por_formato
from typing import Annotated
from app.core.security import TokenData
from app.dependencies import retornar_jogador_atual, permitir_leitura_publica
from app.models import Jogador

router = APIRouter(
    prefix="/ranking",
    tags=["Ranking"])

# Ranking agregado entre lojas (jogador/torneio/rodada de TODA a
# plataforma, não de uma loja só) — a mesma classe de leitura deliberadamente
# cross-tenant de GET /lojas/torneios/, sem a qual a policy de RLS de
# jogadortorneiolink/rodada/torneio ficaria fail-closed aqui (ver
# dependencies.py:permitir_leitura_publica).

@router.get("/geral", response_model=list[Ranking])
def get_ranking_geral(session: SessionDep, _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)]):
    ranking = calcula_ranking_geral(session)
    return ranking

@router.get("/lojas", response_model=list[RankingPorLoja])
def get_ranking_geral_por_loja(
    session: SessionDep,
    _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)],
    mes: Annotated[int | None, Query(ge=1, le=12)] = None,
):
    ranking = calcula_ranking_geral_por_loja(session, mes)
    return ranking

@router.get("/desempenho",response_model=list[RankingPorFormato])
def get_desempenho_por_formato(
    session: SessionDep,
    usuario: Annotated[TokenData, Depends(retornar_jogador_atual)],
    _leitura_publica: Annotated[None, Depends(permitir_leitura_publica)],
):
    jogador = session.get(Jogador, usuario.id)
    desempenho = desempenho_por_formato(session,jogador)
    return desempenho