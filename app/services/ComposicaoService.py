from sqlmodel import select
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.models import (
    ComposicaoPartida,
    ComposicaoPartidaUnidade,
    JogadorTorneioLink,
    LojaJogadorLink,
    LojaJogadorOrganizadorTCG,
    RepresentacaoComposicao,
    RodadaComposicao,
)
from app.utils.Enums import TCG

# Só Pokémon TCG usa o conceito de "representação" (ícone de arquétipo com 2
# unidades) — Pokémon VGC/GO não têm deck nem representação de deck, só a
# composição completa (o time de 6 Pokémon em si, via JogadorComposicaoUnidade
# / ComposicaoUnidadesModal, que já é genérico por `tcg`). Ver docs/COMPOSICAO.md.
JOGOS_COM_REPRESENTACAO_DECK = (TCG.POKEMON,)

# Pokémon GO tem uma peculiaridade que TCG/VGC não têm: o jogador leva um time
# de 6 Pokémon pro torneio (JogadorComposicaoUnidade, igual TCG/VGC), mas
# escolhe só 3 desses 6 pra jogar em CADA partida — um recorte que muda de
# rodada pra rodada, sem nunca alterar o time completo. Pra TCG/VGC a
# composição "usada na partida" é sempre a composição inteira, então nem faz
# sentido editar por rodada — ver ComposicaoPartida/RodadaComposicao em
# app/models.py e docs/COMPOSICAO.md.
JOGOS_COM_COMPOSICAO_POR_PARTIDA = (TCG.POKEMON_GO,)


def verificar_e_organizador(session: SessionDep, usuario: TokenData):
    """Representações de composição são globais (compartilhadas entre lojas),
    mas só quem organiza algo (loja, ou jogador que organiza pelo menos uma
    loja) pode cadastrar novas — evita que qualquer jogador comum polua o
    catálogo."""
    if usuario.tipo == "loja":
        return

    if usuario.tipo == "jogador":
        organiza_alguma_loja = session.exec(
            select(LojaJogadorOrganizadorTCG)
            .join(LojaJogadorLink, LojaJogadorOrganizadorTCG.loja_jogador_link_id == LojaJogadorLink.id)
            .where(LojaJogadorLink.jogador_id == usuario.id)
        ).first()

        if not organiza_alguma_loja:
            raise TopDeckedException.forbidden(
                "Apenas organizadores podem cadastrar representações de composição")
        return

    raise TopDeckedException.forbidden()


def retornar_representacao_completa(representacao: RepresentacaoComposicao) -> dict:
    return {
        "id": representacao.id,
        "tcg": representacao.tcg,
        "nome": representacao.nome,
        "unidades": [
            {
                "id": p.unidade.id,
                "tcg": p.unidade.tcg,
                "external_id": p.unidade.external_id,
                "nome": p.unidade.nome,
            }
            for p in representacao.unidades
        ],
    }


def _clonar_time_em_composicao_partida(session: SessionDep, link: JogadorTorneioLink) -> ComposicaoPartida:
    """Cria uma ComposicaoPartida nova como cópia fiel do time completo que o
    jogador levou pro torneio (`link.composicao_unidades`) — a cópia é
    independente: editar a ComposicaoPartida depois (só permitido pra
    JOGOS_COM_COMPOSICAO_POR_PARTIDA) nunca volta a afetar
    JogadorComposicaoUnidade."""
    composicao_partida = ComposicaoPartida()
    session.add(composicao_partida)
    session.flush()

    for unidade in link.composicao_unidades:
        session.add(ComposicaoPartidaUnidade(
            composicao_partida_id=composicao_partida.id,
            unidade_catalogo_id=unidade.unidade_catalogo_id,
            quantidade=unidade.quantidade,
        ))

    return composicao_partida


def garantir_composicao_partida(session: SessionDep, rodada_id: int, link: JogadorTorneioLink, jogo: TCG) -> RodadaComposicao:
    """Garante que exista uma RodadaComposicao pra essa (rodada, participação),
    chamada por RodadaService.nova_rodada pra cada lado de toda rodada nova
    (inclusive o jogador sozinho num bye). Pra jogos fora de
    JOGOS_COM_COMPOSICAO_POR_PARTIDA (TCG, VGC), reaproveita o mesmo
    ComposicaoPartida.id já usado na rodada anterior dessa participação — a
    composição não muda partida a partida pra esses jogos, então criar uma
    ComposicaoPartida idêntica a cada rodada seria só desperdício. Só Pokémon
    GO ganha uma ComposicaoPartida nova a cada rodada (clonada do time
    completo, seção 5.1 de docs/COMPOSICAO.md), pra permitir escolher um
    recorte de 3 Pokémon diferente por partida via
    PATCH .../composicao-partida sem afetar nem as rodadas passadas nem o
    time completo."""
    rodada_anterior = session.exec(
        select(RodadaComposicao)
        .where(RodadaComposicao.jogador_torneio_link_id == link.id)
        .order_by(RodadaComposicao.id.desc())
    ).first()

    if rodada_anterior and jogo not in JOGOS_COM_COMPOSICAO_POR_PARTIDA:
        composicao_partida_id = rodada_anterior.composicao_partida_id
    else:
        composicao_partida = _clonar_time_em_composicao_partida(session, link)
        composicao_partida_id = composicao_partida.id

    rodada_composicao = RodadaComposicao(
        rodada_id=rodada_id,
        jogador_torneio_link_id=link.id,
        composicao_partida_id=composicao_partida_id,
    )
    session.add(rodada_composicao)
    return rodada_composicao


def retornar_composicao_partida_completa(composicao_partida: ComposicaoPartida) -> dict:
    return {
        "id": composicao_partida.id,
        "unidades": [
            {
                "unidade_catalogo_id": u.unidade_catalogo_id,
                "quantidade": u.quantidade,
                "unidade": {
                    "id": u.unidade.id,
                    "tcg": u.unidade.tcg,
                    "external_id": u.unidade.external_id,
                    "nome": u.unidade.nome,
                },
            }
            for u in composicao_partida.unidades
        ],
    }
