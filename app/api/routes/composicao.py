from typing import Annotated
from fastapi import APIRouter, Depends
from sqlmodel import select
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.dependencies import retornar_usuario_atual
from app.models import UnidadeCatalogo, RepresentacaoComposicao, RepresentacaoComposicaoUnidade
from app.schemas.Composicao import (
    UnidadeCatalogoPublico,
    RepresentacaoComposicaoCriarDTO,
    RepresentacaoComposicaoPublico,
)
from app.utils.Enums import TCG
from app.services.ComposicaoService import (
    verificar_e_organizador,
    retornar_representacao_completa,
    JOGOS_COM_REPRESENTACAO_DECK,
)

# Sem prefixo fixo: expõe tanto o catálogo de unidades (/unidades) quanto
# as representações de composição (/lojas/composicoes/representacoes), mesmo
# padrão de conquista.py.
router = APIRouter(tags=["Composicoes"])


@router.get("/unidades", response_model=list[UnidadeCatalogoPublico])
def buscar_unidades(
    session: SessionDep,
    _: Annotated[TokenData, Depends(retornar_usuario_atual)],
    tcg: TCG = TCG.POKEMON,
    busca: str = "",
):
    query = select(UnidadeCatalogo).where(UnidadeCatalogo.tcg == tcg)

    if busca.strip():
        query = query.where(UnidadeCatalogo.nome.ilike(f"%{busca.strip()}%"))

    query = query.order_by(UnidadeCatalogo.nome).limit(30)

    return session.exec(query).all()


@router.get("/lojas/composicoes/representacoes", response_model=list[RepresentacaoComposicaoPublico])
def listar_representacoes(
    session: SessionDep,
    _: Annotated[TokenData, Depends(retornar_usuario_atual)],
    tcg: TCG = TCG.POKEMON,
):
    representacoes = session.exec(
        select(RepresentacaoComposicao)
        .where(RepresentacaoComposicao.tcg == tcg)
        .order_by(RepresentacaoComposicao.nome)
    ).all()

    return [retornar_representacao_completa(r) for r in representacoes]


@router.post("/lojas/composicoes/representacoes", response_model=RepresentacaoComposicaoPublico)
def criar_representacao(
    session: SessionDep,
    dados: RepresentacaoComposicaoCriarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    verificar_e_organizador(session, usuario)

    if dados.tcg not in JOGOS_COM_REPRESENTACAO_DECK:
        raise TopDeckedException.bad_request(
            f"{dados.tcg} não tem representação de deck — só a composição completa (time) se aplica"
        )

    unidade_1 = session.get(UnidadeCatalogo, dados.unidade_1_id)
    unidade_2 = session.get(UnidadeCatalogo, dados.unidade_2_id)

    if not unidade_1 or not unidade_2:
        raise TopDeckedException.not_found("Unidade não encontrada no catálogo")

    if unidade_1.tcg != dados.tcg or unidade_2.tcg != dados.tcg:
        raise TopDeckedException.bad_request(
            "As unidades escolhidas não pertencem ao TCG da representação")

    nome = dados.nome or f"{unidade_1.nome.title()} {unidade_2.nome.title()}"

    representacao = RepresentacaoComposicao(tcg=dados.tcg, nome=nome)
    session.add(representacao)
    session.commit()
    session.refresh(representacao)

    session.add(RepresentacaoComposicaoUnidade(
        representacao_id=representacao.id, ordem=0, unidade_catalogo_id=unidade_1.id))
    session.add(RepresentacaoComposicaoUnidade(
        representacao_id=representacao.id, ordem=1, unidade_catalogo_id=unidade_2.id))
    session.commit()
    session.refresh(representacao)

    return retornar_representacao_completa(representacao)
