from sqlmodel import select
from fastapi import UploadFile
import xml.etree.ElementTree as ET
from app.core.exception import TopDeckedException
from app.core.db import SessionDep
from app.utils.datetimeUtil import parse_data, parse_datetime
from app.models import Rodada, Torneio, Jogador, JogadorTorneioLink, StatusTorneio, GameID, LojaJogadorLink
from app.utils.Enums import TipoTorneio, TCG


def importar_torneio(session: SessionDep, arquivo: UploadFile, loja_id: int):
    dados = arquivo.file.read()
    try:
        xml = ET.fromstring(dados)
    except ET.ParseError:
        raise TopDeckedException.bad_request("Arquivo XML inválido")

    torneio = _importar_metadados(xml, loja_id)

    if session.get(Torneio, torneio.id):
        raise TopDeckedException.bad_request(
            f"Torneio já criado anteriormente")

    session.add(torneio)
    session.commit()
    session.refresh(torneio)

    jogadores_dict = _criar_relacao_jogador_torneio(xml, torneio, session)

    _importar_rodadas(xml, jogadores_dict, torneio.id, session)

    return torneio


def _importar_metadados(xml: ET.Element, loja_id: int):
    dados = xml.find("data")
    if dados is None:
        raise TopDeckedException.bad_request(
            "Bloco 'data' não encontrado no XML")

    id = dados.findtext("id")
    nome = dados.findtext("name")
    cidade = dados.findtext("city")
    estado = dados.findtext("state")
    tempo_por_rodada = dados.findtext("roundtime", default="30")
    data_inicio_str = dados.findtext("startdate")

    if not cidade or not data_inicio_str:
        raise TopDeckedException.bad_request(
            "Cidade ou data de início ausentes")

    data_inicio = parse_data(data_inicio_str)
    descricao = f"{nome} {data_inicio}"
    novo_torneio = Torneio(nome=nome,
                           descricao=descricao,
                           cidade=cidade,
                           estado=estado,
                           tempo_por_rodada=tempo_por_rodada,
                           data_inicio=data_inicio,
                           loja_id=loja_id,
                           status=StatusTorneio.FINALIZADO,
                           tipo=TipoTorneio.IMPORTADO)
    if id.strip() != "":
        novo_torneio.id = id
    return novo_torneio


def _criar_relacao_jogador_torneio(xml: ET.Element, torneio: Torneio, session: SessionDep):
    jogadores_dict = {}

    dados = xml.find("players")

    if dados is None:
        return jogadores_dict

    for jogador in dados.findall("player"):
        gameid_importado = jogador.attrib.get("userid")
        primeiro_nome = jogador.findtext("firstname", "").strip()
        ultimo_nome = jogador.findtext("lastname", "").strip()
        nome = f"{primeiro_nome} {ultimo_nome}".strip()
        jogador_id = None

        jogador_existente = session.exec(
            select(Jogador)
            .join(GameID, Jogador.id == GameID.jogador_id)
            .where(GameID.id == gameid_importado and GameID.tcg == TCG.POKEMON)
        ).first()

        if jogador_existente:
            jogador_id = jogador_existente.id
            link_loja = session.exec(select(LojaJogadorLink)
                                    .where((LojaJogadorLink.loja_id == torneio.loja_id) &
                                            (LojaJogadorLink.jogador_id == jogador_existente.id))).first()
            if not link_loja:
                novo_link_loja = LojaJogadorLink(jogador_id=jogador_existente.id,
                                                 game_id=gameid_importado,
                                                 tcg=TCG.POKEMON,
                                                 apelido=nome,
                                                 loja_id=torneio.loja_id, quantidade=0)
                session.add(novo_link_loja)
            
        participacao = JogadorTorneioLink(
            jogador_id=jogador_id,
            torneio_id=torneio.id,
            gameid_importado=gameid_importado,
            apelido=nome,
        )

        session.add(participacao)
        session.commit()
        session.refresh(participacao)

        jogadores_dict[gameid_importado] = participacao.id

    return jogadores_dict


def _importar_rodadas(xml: ET.Element, jogadores_dict: dict, torneio_id: str, session: SessionDep):
    pods = xml.find("pods").findall("pod")
    rodadas = []
    for pod in pods:
        rodadas.extend(pod.find("rounds").findall("round"))

    for rodada in rodadas:
        num_rodada = int(rodada.get("number"))
        partidas = rodada.find("matches")

        _importar_partidas(partidas, jogadores_dict, torneio_id, num_rodada, session)


def _importar_partidas(partidas: ET.Element, jogadores_dict: dict, torneio_id: str, num_rodada: int, session: SessionDep):
    partidas_criadas = []
    for partida in partidas.findall("match"):
        jogador1_id = None
        jogador2_id = None

        jogador = partida.find("player")
        if jogador is not None:
            jogador1_id = jogador.get("userid")
        else:
            jogador1_id = partida.find("player1").get("userid")
            jogador2_id = partida.find("player2").get("userid")

        vencedor = int(partida.get("outcome"))

        if vencedor != 2:
            vencedor = jogador1_id
        elif vencedor == 2:
            vencedor = jogador2_id

        mesa = int(partida.findtext("tablenumber"))

        timestamp_str = partida.findtext("timestamp")
        data_inicio = parse_datetime(timestamp_str)

        partida = Rodada(
            jogador1_id=jogadores_dict[jogador1_id],
            jogador2_id=jogadores_dict[jogador2_id],
            vencedor_id=jogadores_dict[vencedor],
            torneio_id=torneio_id,
            num_rodada=num_rodada,
            mesa=mesa,
            data_de_inicio=data_inicio,
            finalizada=True
        )
        session.add(partida)
        session.commit()
        session.refresh(partida)
        partidas_criadas.append(partida)

    return partidas_criadas
