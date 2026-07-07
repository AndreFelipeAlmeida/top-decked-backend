from datetime import datetime
from sqlmodel import select
from fastapi import UploadFile
import xml.etree.ElementTree as ET
from app.core.exception import TopDeckedException
from app.core.db import SessionDep
from app.utils.datetimeUtil import parse_data, parse_datetime
from app.models import Rodada, Torneio, JogadorTorneioLink, StatusTorneio, JogadorCriado, LojaJogadorLink
from app.utils.Enums import TipoTorneio, TCG
from app.services.ConquistaService import recalcular_conquistas_jogador


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
    inicio_real, fim_real = _importar_rodadas(xml, jogadores_dict, torneio.id, session)

    torneio.inicio_real = inicio_real
    torneio.fim_real = fim_real
    # Torneio importado é histórico, não uma reserva de vagas futura — "vagas"
    # aqui deve refletir quantos jogadores de fato participaram.
    torneio.vagas = len(jogadores_dict)
    session.add(torneio)
    session.commit()
    session.refresh(torneio)

    # Torneio importado já nasce FINALIZADO — recalcula conquistas de quem
    # conseguimos identificar como jogador cadastrado (ver docs/CONQUISTAS.md).
    jogadores_ids = session.exec(
        select(JogadorCriado.jogador_id)
        .join(JogadorTorneioLink, JogadorTorneioLink.jogador_criado_id == JogadorCriado.id)
        .where(
            (JogadorTorneioLink.torneio_id == torneio.id) &
            (JogadorCriado.jogador_id.is_not(None))
        )
        .distinct()
    ).all()
    for jogador_id in jogadores_ids:
        recalcular_conquistas_jogador(session, jogador_id)

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
    data_planejada_str = dados.findtext("startdate")

    if not cidade or not data_planejada_str:
        raise TopDeckedException.bad_request(
            "Cidade ou data de início ausentes")

    data_planejada = parse_data(data_planejada_str)
    descricao = f"{nome} {data_planejada}"
    novo_torneio = Torneio(nome=nome,
                           descricao=descricao,
                           cidade=cidade,
                           estado=estado,
                           tempo_por_rodada=tempo_por_rodada,
                           data_planejada=data_planejada,
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

        # .tdf importado é sempre do Pokémon TCG — a âncora (JogadorCriado) é
        # buscada/criada por (tcg, game_id), nunca por Jogador direto: mesmo
        # que o jogador já tenha conta real, é o JogadorCriado que "segura" a
        # participação (ver docs/JOGADORES.md).
        jogador_criado = session.exec(
            select(JogadorCriado).where(
                (JogadorCriado.game_id == gameid_importado) &
                (JogadorCriado.tcg == TCG.POKEMON)
            )
        ).first()

        if not jogador_criado:
            jogador_criado = JogadorCriado(
                game_id=gameid_importado,
                tcg=TCG.POKEMON,
                apelido=nome,
            )
            session.add(jogador_criado)
            session.flush()
            session.refresh(jogador_criado)

        if jogador_criado.jogador_id:
            link_loja = session.exec(select(LojaJogadorLink)
                                    .where((LojaJogadorLink.loja_id == torneio.loja_id) &
                                            (LojaJogadorLink.jogador_id == jogador_criado.jogador_id))).first()
            if not link_loja:
                novo_link_loja = LojaJogadorLink(jogador_id=jogador_criado.jogador_id,
                                                 apelido=nome,
                                                 loja_id=torneio.loja_id)
                session.add(novo_link_loja)

        participacao = JogadorTorneioLink(
            jogador_criado_id=jogador_criado.id,
            torneio_id=torneio.id,
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

    inicio_real = _calcular_inicio_real(rodadas)
    fim_real = _calcular_fim_real(rodadas)

    for rodada in rodadas:
        num_rodada = int(rodada.get("number"))
        partidas = rodada.find("matches")

        _importar_partidas(partidas, jogadores_dict, torneio_id, num_rodada, session)

    return inicio_real, fim_real


def _timestamps_da_rodada(rodadas: list[ET.Element], numero: int) -> list[datetime]:
    stamps = []
    for rodada in rodadas:
        if int(rodada.get("number")) != numero:
            continue
        for match in rodada.find("matches").findall("match"):
            ts = match.findtext("timestamp")
            if ts:
                stamps.append(parse_datetime(ts))
    return stamps


def _calcular_inicio_real(rodadas: list[ET.Element]) -> datetime | None:
    """Menor timestamp de partida dentro da primeira rodada — usado como
    aproximação de quando o torneio de fato começou (ver docs/CONQUISTAS.md)."""
    if not rodadas:
        return None
    primeira_rodada_num = min(int(r.get("number")) for r in rodadas)
    stamps = _timestamps_da_rodada(rodadas, primeira_rodada_num)
    return min(stamps) if stamps else None


def _calcular_fim_real(rodadas: list[ET.Element]) -> datetime | None:
    """Maior timestamp de partida dentro da última rodada — usado como
    aproximação de quando o torneio de fato terminou (ver docs/CONQUISTAS.md).
    Espelha _calcular_inicio_real (menor timestamp da primeira rodada)."""
    if not rodadas:
        return None
    ultima_rodada_num = max(int(r.get("number")) for r in rodadas)
    stamps = _timestamps_da_rodada(rodadas, ultima_rodada_num)
    return max(stamps) if stamps else None


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
        data_de_inicio = parse_datetime(timestamp_str)

        # Partida "bye" (rodada ímpar): o XML só traz um único <player>, então
        # jogador2_id/vencedor podem ser None aqui — não são gameids reais,
        # então não estão (e não devem estar) em jogadores_dict.
        partida = Rodada(
            jogador1_id=jogadores_dict[jogador1_id],
            jogador2_id=jogadores_dict[jogador2_id] if jogador2_id is not None else None,
            vencedor_id=jogadores_dict[vencedor] if vencedor is not None else None,
            torneio_id=torneio_id,
            num_rodada=num_rodada,
            mesa=mesa,
            data_de_inicio=data_de_inicio,
            finalizada=True
        )
        session.add(partida)
        session.commit()
        session.refresh(partida)
        partidas_criadas.append(partida)

    return partidas_criadas
