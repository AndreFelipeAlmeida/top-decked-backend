from collections import defaultdict
from app.core.db import SessionDep
from app.models import Jogador, JogadorTorneioLink, Torneio, Rodada
from sqlmodel import select
from typing import List
from app.utils.Enums import MesEnum
from app.utils.RankingUtil import calcula_ranking_geral, calcular_taxa_vitoria
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.Enums import StatusTorneio


def posicao_do_jogador(ranking: list, jogador_id: str):
    for index, r in enumerate(ranking, start=1):
        if r.jogador_id == jogador_id:
            return index
    return None

def calcular_estatisticas(session: SessionDep, jogador: Jogador):
    estat_por_mes = _retornar_estatisticas_mensais(session, jogador.pokemon_id)
    torneios_links = session.exec(select(JogadorTorneioLink)
                                  .join(Torneio)
                                  .where(
                                      (Torneio.status == StatusTorneio.FINALIZADO) &
                                      (JogadorTorneioLink.jogador_id == jogador.pokemon_id))).all()
    
    torneio_totais = len(torneios_links)
    torneios_historico = _retornar_estatisticas_torneio(session, jogador, torneios_links)
    taxa_vitoria = calcular_taxa_vitoria(session, jogador)
    rank_geral = posicao_do_jogador(calcula_ranking_geral(session), jogador.pokemon_id)
    rank_mensal = posicao_do_jogador(calcula_ranking_geral(session, data_agora_brasil().month), jogador.pokemon_id)
    rank_anual = posicao_do_jogador(calcula_ranking_geral(session, data_agora_brasil().year), jogador.pokemon_id)
    vde = retornar_vde_jogador_finalizados(session, jogador.pokemon_id)
    
    return {"estatisticas_anuais": estat_por_mes, 
            "torneio_totais" : torneio_totais,
            "taxa_vitoria" : taxa_vitoria,
            "rank_geral" : rank_geral,
            "rank_mensal": rank_mensal,
            "rank_anual": rank_anual,
            "historico" : torneios_historico,
            **vde}

def _retornar_estatisticas_torneio(session: SessionDep, jogador: Jogador, 
                                   torneios_links: List["JogadorTorneioLink"]):
    estatisticas = []
    for link in torneios_links:
        colocacao = colocacao_jogador(session, link.torneio, jogador)
        estatisticas.append({
            "id" : link.torneio_id,
            "nome" : link.torneio.nome,
            "data_inicio" : link.torneio.data_inicio,
            "colocacao": colocacao,
            "participantes": len(link.torneio.jogadores),
            "pontuacao": link.pontuacao_com_regras
        })
    return estatisticas
        

def _retornar_estatisticas_mensais(session: SessionDep, jogador_id: str):
    rodadas = session.exec(
        select(Rodada).join(Torneio).where(
            (Torneio.status == StatusTorneio.FINALIZADO) &
            ((Rodada.jogador1_id == jogador_id) |
            (Rodada.jogador2_id == jogador_id))
        )
    ).all()
    links = session.exec(
        select(JogadorTorneioLink)
        .join(Torneio)
        .where((Torneio.status == StatusTorneio.FINALIZADO) &
               (JogadorTorneioLink.jogador_id == jogador_id))
    ).all()

    estatisticas = defaultdict(lambda: {"pontos": 0, "vitorias": 0, "derrotas": 0, "empates": 0})
    for link in links:
        ano = link.torneio.data_inicio.year
        mes = link.torneio.data_inicio.month
        chave = (ano, mes)
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
        if j.jogador_id == jogador.pokemon_id:
            return i
    return None

def calcular_forca_oponente(session: SessionDep, torneio: Torneio, link: JogadorTorneioLink):
    oponentes_vencidos = []
    rodadas = session.exec(
        select(Rodada).where(Rodada.torneio_id == torneio.id)
    ).all()

    for rodada in rodadas:
        if rodada.vencedor == link.jogador_id:
            oponente_id = rodada.jogador2_id if rodada.jogador1_id == link.jogador_id else rodada.jogador1_id
            oponentes_vencidos.append(oponente_id)
    
    if not oponentes_vencidos:
        return 0

    taxas = []
    for op_id in oponentes_vencidos:
        if op_id:
            op_jogador = session.exec(select(Jogador).where(Jogador.pokemon_id == op_id)).first()
            taxas.append(calcular_taxa_vitoria(session, op_jogador))

    return sum(taxas) / len(taxas) if len(taxas) != 0 else 0

def _descobrir_oponente(rodada: Rodada, jogador: str):
    oponente = "bye"
    if rodada.jogador1_id == jogador and rodada.jogador2_id:
        oponente = rodada.jogador2_id
    elif rodada.jogador2_id == jogador and rodada.jogador1_id:
        oponente = rodada.jogador1_id
    
    return oponente

def _processar_rodada(oponentes_salvos: dict, rodada: Rodada, jogador: str, oponente : str):
    if rodada.vencedor == oponente:
        oponentes_salvos[oponente]["derrotas"] += 1
    elif rodada.vencedor == jogador:
        oponentes_salvos[oponente]["vitorias"] += 1
    else:
        oponentes_salvos[oponente]["empates"] += 1
    
    return oponentes_salvos
    

def retornar_historico_jogador(session: SessionDep, jogador: Jogador):
    oponentes_salvos = {}
    
    rodadas = session.exec(select(Rodada)
                           .where((Rodada.jogador1_id == jogador.pokemon_id)
                                  | (Rodada.jogador2_id == jogador.pokemon_id)))
    
    for rodada in rodadas:
        oponente = _descobrir_oponente(rodada, jogador.pokemon_id)
        
        if oponente not in oponentes_salvos:
            if oponente != "bye":
                op_jog = session.exec(select(Jogador).where(Jogador.pokemon_id == oponente)).first()
            
            historico_op = {
                "id" : oponente,
                "nome" : op_jog.nome if oponente != "bye" else oponente,
                "vitorias" : 0,
                "derrotas" : 0,
                "empates" : 0
            }
            oponentes_salvos[oponente] = historico_op
        
        oponentes_salvos = _processar_rodada(
            oponentes_salvos, rodada, jogador.pokemon_id, oponente)
    
    return list(oponentes_salvos.values())


def retornar_vde_jogador(session: SessionDep, jogador_id: str, torneio: Torneio | None = None):
    consulta = select(Rodada).where((Rodada.jogador1_id == jogador_id)
                                     | (Rodada.jogador2_id == jogador_id))
    
    if torneio:
        consulta = consulta.where(Rodada.torneio_id == torneio.id)
    
    rodadas = session.exec(consulta).all()
    
    vde = {
        "vitorias": 0,
        "derrotas": 0,
        "empates": 0
    }
    for rodada in rodadas:
        if not rodada.finalizada:
            continue
        
        oponente = _descobrir_oponente(rodada, jogador_id)

        if rodada.vencedor == oponente:
            vde["derrotas"] += 1
        elif rodada.vencedor == jogador_id:
            vde["vitorias"] += 1
        else:
            vde["empates"] += 1

    return vde


def retornar_todas_rodadas(session: SessionDep, jogador: Jogador):
    rodadas = session.exec(
        select(Rodada).where(
            (Rodada.jogador1_id == jogador.pokemon_id) |
            (Rodada.jogador2_id == jogador.pokemon_id)
        )
    ).all()

    result = []
    for rodada in rodadas:
        oponente = session.exec(select(Jogador)
                                .where(Jogador.pokemon_id == (_descobrir_oponente(rodada, jogador.pokemon_id)))).first()

        if rodada.vencedor and rodada.vencedor != jogador.pokemon_id:
            resultado = "derrota"
        elif rodada.jogador1_id and rodada.jogador2_id and not rodada.vencedor:
            resultado = "empate"
        else:
            resultado = "vitoria"
        torneio = session.get(Torneio, rodada.torneio_id)
        result.append({
            "data": rodada.data_de_inicio,
            "loja": torneio.loja.nome,
            "rodada" : rodada.id,
            "mesa": rodada.mesa,
            "resultado": resultado,
            "oponente": oponente.nome if oponente else "bye",
        })
        
    return result


def retornar_vde_jogador_finalizados(session: SessionDep, jogador_id: str, torneio: Torneio | None = None):
    consulta = select(Rodada).join(Torneio).where(
        (Torneio.status == StatusTorneio.FINALIZADO) &
        (Rodada.jogador1_id == jogador_id) | 
        (Rodada.jogador2_id == jogador_id))

    if torneio:
        consulta = consulta.where(Rodada.torneio_id == torneio.id)

    rodadas = session.exec(consulta).all()

    vde = {
        "vitorias": 0,
        "derrotas": 0,
        "empates": 0
    }
    for rodada in rodadas:
        if not rodada.finalizada:
            continue

        oponente = _descobrir_oponente(rodada, jogador_id)

        if rodada.vencedor == oponente:
            vde["derrotas"] += 1
        elif rodada.vencedor == jogador_id:
            vde["vitorias"] += 1
        else:
            vde["empates"] += 1

    return vde