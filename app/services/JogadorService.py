from collections import defaultdict
from app.core.db import SessionDep
from app.models import Jogador, JogadorTorneioLink, Torneio, Rodada, JogadorCriado
from sqlmodel import select
from sqlalchemy import func
from typing import List
from app.utils.Enums import MesEnum, TCG
from app.services.RankingService import calcula_ranking_geral, calcular_taxa_vitoria
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.Enums import StatusTorneio, TipoTorneio
from app.utils.TorneioDataUtil import data_efetiva_torneio
from app.schemas.GameID import GameIDPublico
from app.core.exception import TopDeckedException


def posicao_do_jogador(ranking: list, jogador_id: int):
    for index, r in enumerate(ranking, start=1):
        if r.jogador_id == jogador_id:
            return index
    return None


def calcular_estatisticas(
    session: SessionDep, jogador: Jogador, loja_id: int | None = None, tcg: str | None = None,
):
    estat_por_mes = _retornar_estatisticas_mensais(session, jogador.id, loja_id, tcg)
    # Um jogador só tem UMA linha de JogadorTorneioLink por torneio (fonte
    # única de verdade — ver TipoParticipanteTorneio.JOGADOR_E_JUIZ), então
    # essa contagem já não precisa de deduplicação nenhuma.
    query_torneios_links = (select(JogadorTorneioLink)
                            .join(Torneio)
                            .join(JogadorCriado, JogadorCriado.id == JogadorTorneioLink.jogador_criado_id)
                            .where(
                                (Torneio.status == StatusTorneio.FINALIZADO) &
                                (JogadorCriado.jogador_id == jogador.id)))
    if loja_id is not None:
        query_torneios_links = query_torneios_links.where(Torneio.loja_id == loja_id)
    if tcg is not None:
        query_torneios_links = query_torneios_links.where(Torneio.jogo == tcg)
    torneios_links = session.exec(query_torneios_links).all()

    torneio_totais = len(torneios_links)
    torneios_historico = _retornar_estatisticas_torneio(
        session, jogador, torneios_links)
    taxa_vitoria = calcular_taxa_vitoria(session, jogador, loja_id=loja_id, tcg=tcg)
    rank_geral = posicao_do_jogador(calcula_ranking_geral(session, loja_id=loja_id, tcg=tcg), jogador.id)
    rank_mensal = posicao_do_jogador(calcula_ranking_geral(
        session, mes=data_agora_brasil().month, loja_id=loja_id, tcg=tcg), jogador.id)
    rank_anual = posicao_do_jogador(calcula_ranking_geral(
        session, ano=data_agora_brasil().year, loja_id=loja_id, tcg=tcg), jogador.id)
    vde = retornar_vde_jogador_finalizados(session, jogador.id, loja_id=loja_id, tcg=tcg)

    return {"estatisticas_anuais": estat_por_mes,
            "torneio_totais": torneio_totais,
            "taxa_vitoria": taxa_vitoria,
            "rank_geral": rank_geral,
            "rank_mensal": rank_mensal,
            "rank_anual": rank_anual,
            "historico": torneios_historico,
            **vde}


def _retornar_estatisticas_torneio(session: SessionDep, jogador: Jogador,
                                   torneios_links: List["JogadorTorneioLink"]):
    estatisticas = []
    for link in torneios_links:
        colocacao = colocacao_jogador(session, link.torneio, jogador)
        estatisticas.append({
            "id": link.torneio_id,
            "nome": link.torneio.nome,
            # Estes torneios já são todos FINALIZADO (filtrado pelo chamador)
            # — a data real vale, não a planejada (ver TorneioDataUtil).
            "data_planejada": data_efetiva_torneio(link.torneio),
            "colocacao": colocacao,
            "participantes": len(link.torneio.jogadores),
            "pontuacao": link.pontuacao_com_regras
        })
    return estatisticas


def _retornar_estatisticas_mensais(
    session: SessionDep, jogador_id: str, loja_id: int | None = None, tcg: str | None = None,
):
    query_rodadas = select(Rodada).join(Torneio).where(
        (Torneio.status == StatusTorneio.FINALIZADO) &
        ((Rodada.jogador1_id == jogador_id) |
         (Rodada.jogador2_id == jogador_id))
    )
    query_links = (
        select(JogadorTorneioLink)
        .join(Torneio)
        .join(JogadorCriado, JogadorCriado.id == JogadorTorneioLink.jogador_criado_id)
        .where((Torneio.status == StatusTorneio.FINALIZADO) &
               (JogadorCriado.jogador_id == jogador_id))
    )
    if loja_id is not None:
        query_rodadas = query_rodadas.where(Torneio.loja_id == loja_id)
        query_links = query_links.where(Torneio.loja_id == loja_id)
    if tcg is not None:
        query_rodadas = query_rodadas.where(Torneio.jogo == tcg)
        query_links = query_links.where(Torneio.jogo == tcg)

    rodadas = session.exec(query_rodadas).all()
    links = session.exec(query_links).all()

    estatisticas = defaultdict(
        lambda: {"pontos": 0, "vitorias": 0, "derrotas": 0, "empates": 0})
    for link in links:
        data = data_efetiva_torneio(link.torneio)
        chave = (data.year, data.month)
        estatisticas[chave]["pontos"] += link.pontuacao_com_regras or 0

    for rodada in rodadas:
        ano = rodada.data_de_inicio.year
        mes = rodada.data_de_inicio.month
        chave = (ano, mes)

        if not rodada.vencedor:
            estatisticas[chave]["empates"] += 1
        elif rodada.vencedor == jogador_id:
            estatisticas[chave]["vitorias"] += 1
        else:
            estatisticas[chave]["derrotas"] += 1

    resultado_formatado = []
    for (ano, mes), dados in sorted(estatisticas.items()):
        resultado_formatado.append({
            "mes": MesEnum.abreviacao(mes),
            "ano": ano,
            "pontos": dados["pontos"],
            "vitorias": dados["vitorias"],
            "derrotas": dados["derrotas"],
            "empates": dados["empates"]
        })

    return resultado_formatado


def colocacao_jogador(session: SessionDep, torneio: Torneio, jogador: Jogador):
    ranking = []
    for j in torneio.jogadores:
        pontuacao = j.pontuacao
        forca_oponentes = calcular_forca_oponente(session, torneio, j)
        ranking.append((j, pontuacao, forca_oponentes))

    ranking.sort(key=lambda x: (x[1], x[2]), reverse=True)

    for i, (j, _, _) in enumerate(ranking, start=1):
        if j.jogador_criado and j.jogador_criado.jogador_id == jogador.id:
            return i
    return None


def calcular_forca_oponente(session: SessionDep, torneio: Torneio, link: JogadorTorneioLink):
    oponentes_vencidos = []
    rodadas = session.exec(
        select(Rodada).where(Rodada.torneio_id == torneio.id)
    ).all()

    for rodada in rodadas:
        if rodada.vencedor_id == link.id:
            oponente_link_id = rodada.jogador2_id if rodada.jogador1_id == link.id else rodada.jogador1_id
            if oponente_link_id:
                oponentes_vencidos.append(oponente_link_id)

    if not oponentes_vencidos:
        return 0

    taxas = []
    for op_link_id in oponentes_vencidos:
        oponente_link = session.get(JogadorTorneioLink, op_link_id)
        if oponente_link and oponente_link.jogador_criado and oponente_link.jogador_criado.jogador_id:
            op_jogador = session.get(Jogador, oponente_link.jogador_criado.jogador_id)
            if op_jogador:
                taxas.append(calcular_taxa_vitoria(session, op_jogador))

    return sum(taxas) / len(taxas) if len(taxas) != 0 else 0


def _descobrir_oponente(rodada: Rodada, jogador: str):
    oponente = "bye"
    if rodada.jogador1_id == jogador and rodada.jogador2_id:
        oponente = rodada.jogador2_id
    elif rodada.jogador2_id == jogador and rodada.jogador1_id:
        oponente = rodada.jogador1_id

    return oponente


def _processar_rodada(oponentes_salvos: dict, rodada: Rodada, jogador: str, oponente: str):
    if oponente == "bye":
        oponentes_salvos[oponente]["vitorias"] += 1
    elif rodada.vencedor == oponente:
        oponentes_salvos[oponente]["derrotas"] += 1
    elif rodada.vencedor == jogador:
        oponentes_salvos[oponente]["vitorias"] += 1
    else:
        oponentes_salvos[oponente]["empates"] += 1

    return oponentes_salvos


def retornar_historico_jogador(session: SessionDep, jogador: Jogador):
    oponentes_salvos = {}

    rodadas = session.exec(select(Rodada)
                           .where((Rodada.jogador1_id == jogador.id)
                                  | (Rodada.jogador2_id == jogador.id)))

    for rodada in rodadas:
        oponente = _descobrir_oponente(rodada, jogador.id)

        if oponente not in oponentes_salvos:
            if oponente != "bye":
                op_jog = session.exec(select(Jogador).where(
                    Jogador.id == oponente)).first()

            historico_op = {
                "id": oponente,
                "nome": op_jog.nome if oponente != "bye" else oponente,
                "vitorias": 0,
                "derrotas": 0,
                "empates": 0
            }
            oponentes_salvos[oponente] = historico_op

        oponentes_salvos = _processar_rodada(
            oponentes_salvos, rodada, jogador.id, oponente)

    return list(oponentes_salvos.values())


def _links_do_jogador(
    session: SessionDep,
    jogador_id: int,
    loja_id: int | None = None,
    tcg: str | None = None,
    torneio_id: str | None = None,
) -> List["JogadorTorneioLink"]:
    query = (
        select(JogadorTorneioLink)
        .join(JogadorCriado, JogadorCriado.id == JogadorTorneioLink.jogador_criado_id)
        .where(JogadorCriado.jogador_id == jogador_id)
    )
    if torneio_id is not None or loja_id is not None or tcg is not None:
        query = query.join(Torneio, Torneio.id == JogadorTorneioLink.torneio_id)
        if torneio_id is not None:
            query = query.where(Torneio.id == torneio_id)
        if loja_id is not None:
            query = query.where(Torneio.loja_id == loja_id)
        if tcg is not None:
            query = query.where(Torneio.jogo == tcg)
    return session.exec(query).all()


def retornar_vde_jogador(session: SessionDep, jogador_id: int | None, torneio: Torneio | None = None):
    vde = {
        "vitorias": 0,
        "derrotas": 0,
        "empates": 0
    }

    if not isinstance(jogador_id, int):
        return vde

    links = _links_do_jogador(session, jogador_id, torneio_id=torneio.id if torneio else None)
    link_ids = {link.id for link in links}
    if not link_ids:
        return vde

    consulta = select(Rodada).where(
        Rodada.jogador1_id.in_(link_ids) | Rodada.jogador2_id.in_(link_ids)
    )
    if torneio:
        consulta = consulta.where(Rodada.torneio_id == torneio.id)

    for rodada in session.exec(consulta).all():
        if not rodada.finalizada:
            continue

        meu_link_id = rodada.jogador1_id if rodada.jogador1_id in link_ids else rodada.jogador2_id
        if rodada.vencedor_id == meu_link_id:
            vde["vitorias"] += 1
        elif rodada.vencedor_id is not None:
            vde["derrotas"] += 1
        else:
            vde["empates"] += 1

    return vde


def retornar_todas_rodadas(session: SessionDep, jogador: Jogador):
    rodadas = session.exec(
        select(Rodada).where(
            (Rodada.jogador1_id == jogador.id) |
            (Rodada.jogador2_id == jogador.id)
        )
    ).all()

    result = []
    for rodada in rodadas:
        oponente = session.exec(select(Jogador)
                                .where(Jogador.id == (_descobrir_oponente(rodada, jogador.id)))).first()

        if rodada.vencedor and rodada.vencedor != jogador.id:
            resultado = "derrota"
        elif rodada.jogador1_id and rodada.jogador2_id and not rodada.vencedor:
            resultado = "empate"
        else:
            resultado = "vitoria"
        torneio = session.get(Torneio, rodada.torneio_id)
        result.append({
            "data": rodada.data_de_inicio,
            "loja": torneio.loja.nome,
            "rodada": rodada.id,
            "mesa": rodada.mesa,
            "resultado": resultado,
            "oponente": oponente.nome if oponente else "bye",
        })

    return result


def retornar_vde_jogador_finalizados(
    session: SessionDep,
    jogador_id: int | None,
    torneio: Torneio | None = None,
    loja_id: int | None = None,
    tcg: str | None = None,
):
    vde = {
        "vitorias": 0,
        "derrotas": 0,
        "empates": 0
    }

    if not isinstance(jogador_id, int):
        return vde

    links = _links_do_jogador(
        session, jogador_id, loja_id=loja_id, tcg=tcg,
        torneio_id=torneio.id if torneio else None,
    )
    link_ids = {link.id for link in links}
    if not link_ids:
        return vde

    consulta = select(Rodada).join(Torneio).where(
        (Torneio.status == StatusTorneio.FINALIZADO) &
        (Rodada.jogador1_id.in_(link_ids) | Rodada.jogador2_id.in_(link_ids))
    )
    if torneio:
        consulta = consulta.where(Rodada.torneio_id == torneio.id)
    if loja_id is not None:
        consulta = consulta.where(Torneio.loja_id == loja_id)
    if tcg is not None:
        consulta = consulta.where(Torneio.jogo == tcg)

    for rodada in session.exec(consulta).all():
        if not rodada.finalizada:
            continue

        meu_link_id = rodada.jogador1_id if rodada.jogador1_id in link_ids else rodada.jogador2_id
        if rodada.vencedor_id == meu_link_id:
            vde["vitorias"] += 1
        elif rodada.vencedor_id is not None:
            vde["derrotas"] += 1
        else:
            vde["empates"] += 1

    return vde


def contar_impacto_troca_gameid(session: SessionDep, jogador_id: int, tcg: TCG, gameid_atual: str) -> int:
    jogador_criado_atual = session.exec(
        select(JogadorCriado).where(
            (JogadorCriado.jogador_id == jogador_id) &
            (JogadorCriado.tcg == tcg) &
            (JogadorCriado.game_id == gameid_atual)
        )
    ).first()

    if not jogador_criado_atual:
        return 0

    torneios = session.exec(
        select(func.count(JogadorTorneioLink.id))
        .join(Torneio, Torneio.id == JogadorTorneioLink.torneio_id)
        .where(
            (JogadorTorneioLink.jogador_criado_id == jogador_criado_atual.id) &
            (Torneio.tipo == TipoTorneio.IMPORTADO)
        )
    ).one()

    return torneios


def desvincular_gameid_antigo(session: SessionDep, jogador_criado_antigo: JogadorCriado):
    """Ao trocar de GameID, o jogador perde a atribuição (não o histórico em
    si, só a ligação com esta conta) dos torneios importados e créditos de
    loja que apontam pro JogadorCriado antigo — como eles apontam pro
    JogadorCriado (não pro Jogador direto), basta desmarcar jogador_id aqui;
    os vínculos existentes "seguem" automaticamente, sem precisar reatribuir
    linha por linha."""
    jogador_criado_antigo.jogador_id = None
    session.add(jogador_criado_antigo)


def vincular_historico_e_creditos(session: SessionDep, game_ids: List[GameIDPublico], jogador_id: int):
    for game_id in game_ids:
        jogador_criado_existente = session.exec(
            select(JogadorCriado).where(
                (JogadorCriado.game_id == game_id.id) & (JogadorCriado.tcg == game_id.tcg)
            )
        ).first()

        if (jogador_criado_existente and jogador_criado_existente.jogador_id
                and jogador_criado_existente.jogador_id != jogador_id):
            raise TopDeckedException.bad_request("Game ID Já cadastrado em outra conta")

        # JogadorCriado tem UniqueConstraint em (jogador_id, tcg) — um jogador
        # só pode reivindicar um game_id por TCG. Trocar de ID (não só vincular
        # o primeiro) precisa desvincular o JogadorCriado antigo antes, senão
        # o jogador ficaria "dono" de dois JogadorCriado do mesmo TCG ao
        # mesmo tempo (viola a constraint).
        jogador_criado_antigo = session.exec(
            select(JogadorCriado).where(
                (JogadorCriado.jogador_id == jogador_id) & (JogadorCriado.tcg == game_id.tcg)
            )
        ).first()
        novo_id = jogador_criado_existente.id if jogador_criado_existente else None
        if jogador_criado_antigo and jogador_criado_antigo.id != novo_id:
            desvincular_gameid_antigo(session, jogador_criado_antigo)
            session.flush()

        if jogador_criado_existente:
            jogador_criado_existente.jogador_id = jogador_id
            session.add(jogador_criado_existente)
        else:
            session.add(JogadorCriado(game_id=game_id.id, tcg=game_id.tcg, jogador_id=jogador_id))
