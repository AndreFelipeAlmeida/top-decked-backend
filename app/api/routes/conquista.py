from typing import Annotated
from fastapi import APIRouter, Depends
from sqlmodel import col, select
from app.core.db import SessionDep
from app.core.security import TokenData
from app.dependencies import retornar_jogador_atual
from app.models import Conquista, ConquistaNivel, HistoricoConquista, JogadorConquista
from app.schemas.Conquista import (
    ConquistaPublico,
    HistoricoConquistaPublico,
    JogadorConquistaPublico,
)
from app.services.ConquistaService import recalcular_conquistas_jogador

# Sem prefixo fixo no router: expõe tanto o catálogo público (/conquistas)
# quanto sub-recursos do jogador logado (/jogadores/conquistas/...), seguindo
# o mesmo padrão de sub-recurso que /jogadores/estatisticas já usa.
router = APIRouter(tags=["Conquistas"])


@router.get("/conquistas", response_model=list[ConquistaPublico])
def get_catalogo_conquistas(session: SessionDep):
    return session.exec(
        select(Conquista).where(Conquista.ativa)
    ).all()


@router.get("/jogadores/conquistas", response_model=list[JogadorConquistaPublico])
def get_minhas_conquistas(
    session: SessionDep,
    token_data: Annotated[TokenData, Depends(retornar_jogador_atual)],
):
    conquistas = session.exec(
        select(Conquista).where(Conquista.ativa)
    ).all()

    progresso_por_conquista = {
        jc.conquista_id: jc
        for jc in session.exec(
            select(JogadorConquista).where(JogadorConquista.jogador_id == token_data.id)
        ).all()
    }

    resultado = []
    for conquista in conquistas:
        jc = progresso_por_conquista.get(conquista.id)
        resultado.append({
            "conquista": conquista,
            "progresso_atual": jc.progresso_atual if jc else 0,
            "nivel_atual": jc.nivel_atual if jc else 0,
            "nivel_atual_em": jc.nivel_atual_em if jc else None,
        })

    return resultado


@router.get("/jogadores/conquistas/historico", response_model=list[HistoricoConquistaPublico])
def get_historico_conquistas(
    session: SessionDep,
    token_data: Annotated[TokenData, Depends(retornar_jogador_atual)],
):
    registros = session.exec(
        select(HistoricoConquista)
        .where(HistoricoConquista.jogador_id == token_data.id)
        .order_by(col(HistoricoConquista.conquistado_em).desc())
    ).all()

    resultado = []
    for registro in registros:
        nivel_def = session.exec(
            select(ConquistaNivel).where(
                (ConquistaNivel.conquista_id == registro.conquista_id) &
                (ConquistaNivel.nivel == registro.nivel)
            )
        ).first()

        resultado.append({
            "conquista_codigo": registro.conquista.codigo,
            "conquista_nome": registro.conquista.nome,
            "conquista_icone": registro.conquista.icone,
            "categoria": registro.conquista.categoria,
            "nivel": registro.nivel,
            "nome_nivel": nivel_def.nome_nivel if nivel_def else str(registro.nivel),
            "conquistado_em": registro.conquistado_em,
        })

    return resultado


@router.post("/jogadores/conquistas/recalcular", response_model=list[JogadorConquistaPublico])
def recalcular_minhas_conquistas(
    session: SessionDep,
    token_data: Annotated[TokenData, Depends(retornar_jogador_atual)],
):
    subiram_de_nivel = recalcular_conquistas_jogador(session, token_data.id)
    return [
        {
            "conquista": jc.conquista,
            "progresso_atual": jc.progresso_atual,
            "nivel_atual": jc.nivel_atual,
            "nivel_atual_em": jc.nivel_atual_em,
        }
        for jc in subiram_de_nivel
    ]
