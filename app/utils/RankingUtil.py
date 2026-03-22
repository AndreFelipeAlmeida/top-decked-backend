from app.core.db import SessionDep
from app.schemas.Ranking import Ranking, RankingPorLoja, RankingPorFormato
from sqlmodel import select, extract
from app.models import Jogador, JogadorTorneioLink, Rodada, Loja, Torneio
from app.utils.Enums import StatusTorneio, TCG
from collections import defaultdict


def calcula_ranking_geral(session: SessionDep, mes=None, ano=None):
    jogadores = session.exec(
        select(Jogador)
    ).all()
    ranking = []

    for jogador in jogadores:
        total_pontos = 0
        total_torneios = 0
        total_vitorias = 0
        total_derrotas = 0
        total_empates = 0
        game_id = next(
            (g.game_id for g in jogador.tcgs if g.tcg == TCG.POKEMON),
            None
        )

        for link in jogador.torneios:
            torneio = link.torneio
            if not torneio:
                continue

            total_torneios += 1
            total_pontos += int(link.pontuacao_com_regras)

            rodadas = select(Rodada).join(Torneio).where(
                (Torneio.status == StatusTorneio.FINALIZADO) &
                (Rodada.torneio_id == link.torneio_id) &
                ((Rodada.jogador1_id == jogador.id) |
                 (Rodada.jogador2_id == jogador.id))
            )
            if mes:
                rodadas = rodadas.where(
                    extract("month", Rodada.data_de_inicio) == mes)
            if ano:
                rodadas = rodadas.where(
                    extract("year", Rodada.data_de_inicio) == ano)

            rodadas = session.exec(rodadas).all()
            for rodada in rodadas:
                if (rodada.vencedor == jogador.id):
                    total_vitorias += 1
                elif (rodada.vencedor is not None):
                    total_derrotas += 1
                else:
                    total_empates += 1
        if total_pontos == 0:
            continue

        ranking.append(Ranking(
            jogador_id=jogador.id,
            game_id=game_id,
            nome_jogador=jogador.nome,
            pontos=total_pontos,
            torneios=total_torneios,
            vitorias=total_vitorias,
            derrotas=total_derrotas,
            empates=total_empates,
            taxa_vitoria=calcular_taxa_vitoria(session, jogador)
        ))

    ranking.sort(key=lambda x: x.pontos, reverse=True)

    return ranking


def calcula_ranking_geral_por_loja(session: SessionDep, mes: int = None):
    lojas = session.exec(select(Loja)).all()
    jogadores = session.exec(select(Jogador)).all()
    ranking = []
    for loja in lojas:
        for jogador in jogadores:
            links = session.exec(
                select(JogadorTorneioLink)
                .join(JogadorTorneioLink.torneio)
                .where(
                    JogadorTorneioLink.jogador_id == jogador.id,
                    Torneio.loja_id == loja.id))

            if mes is not None:
                links = links.where(
                    extract("month", Torneio.data_inicio) == mes).all()
            if (links == []):
                continue
            total_pontos = 0
            total_torneios = 0
            total_vitorias = 0
            total_derrotas = 0
            total_empates = 0
            for link in links:
                total_torneios += 1
                total_pontos += int(link.pontuacao_com_regras)

                rodadas = session.exec(
                    select(Rodada).where(
                        (Rodada.torneio_id == link.torneio_id) &
                        ((Rodada.jogador1_id == jogador.id) |
                         (Rodada.jogador2_id == jogador.id))
                    )
                ).all()

                for rodada in rodadas:
                    if (rodada.vencedor == jogador.id):
                        total_vitorias += 1
                    elif (rodada.vencedor is not None):
                        total_derrotas += 1
                    else:
                        total_empates += 1

            if total_pontos == 0:
                continue

            total_rodadas = total_vitorias + total_derrotas + total_empates
            taxa_vitoria = int((total_vitorias / total_rodadas)
                               * 100) if total_rodadas > 0 else 0

            ranking.append(RankingPorLoja(
                nome_jogador=jogador.nome,
                nome_loja=loja.nome,
                pontos=total_pontos,
                torneios=total_torneios,
                vitorias=total_vitorias,
                derrotas=total_derrotas,
                empates=total_empates,
                taxa_vitoria=taxa_vitoria
            ))

    ranking.sort(key=lambda x: x.pontos, reverse=True)

    return ranking


def desempenho_por_formato(session: SessionDep, jogador: Jogador) -> list[RankingPorFormato]:
    links = session.exec(
        select(JogadorTorneioLink)
        .join(Torneio)
        .where(
            (Torneio.status == StatusTorneio.FINALIZADO) &
            (JogadorTorneioLink.jogador_id == jogador.id))
    ).all()

    if not links:
        return []

    formatos_data = defaultdict(lambda: {
        "pontos": 0,
        "vitorias": 0,
        "total_partidas": 0
    })

    for link in links:
        formato = link.torneio.formato if link.torneio.formato else "Desconhecido"
        formatos_data[formato]["pontos"] += float(link.pontuacao_com_regras)

        rodadas = session.exec(
            select(Rodada).where(
                (Rodada.torneio_id == link.torneio_id) &
                ((Rodada.jogador1_id == jogador.id) |
                 (Rodada.jogador2_id == jogador.id))
            )
        ).all()

        for rodada in rodadas:
            formatos_data[formato]["total_partidas"] += 1
            if rodada.vencedor == jogador.id:
                formatos_data[formato]["vitorias"] += 1

    ranking = []
    for formato, dados in formatos_data.items():
        total_partidas = dados["total_partidas"]
        taxa_vitoria = round(
            dados["vitorias"] / total_partidas, 2) if total_partidas > 0 else 0.0

        ranking.append(RankingPorFormato(
            formato=formato,
            pontos=dados["pontos"],
            vitorias=dados["vitorias"],
            taxa_vitoria=taxa_vitoria
        ))

    return ranking


def calcular_taxa_vitoria(session: SessionDep, jogador: Jogador):
    vitorias, derrotas, empates = 0, 0, 0

    rodadas = session.exec(select(Rodada)
                           .join(Torneio)
                           .where(
                               (Torneio.status == StatusTorneio.FINALIZADO) &
        ((Rodada.jogador1_id == jogador.id) | (Rodada.jogador2_id == jogador.id))))

    for rodada in rodadas:
        if (rodada.vencedor == jogador.id):
            vitorias += 1
        elif (rodada.vencedor is not None):
            derrotas += 1
        else:
            empates += 1

    total = vitorias + derrotas + empates
    return int((vitorias / total) * 100) if total > 0 else 0
