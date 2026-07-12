from datetime import datetime
from sqlmodel import select
from fastapi import UploadFile, HTTPException
import xml.etree.ElementTree as ET
from app.core.exception import TopDeckedException
from app.core.db import SessionDep
from app.utils.datetimeUtil import parse_data, parse_datetime, agora_brasil
from app.models import Rodada, Torneio, JogadorTorneioLink, StatusTorneio, JogadorCriado, LojaJogadorLink
from app.utils.Enums import TipoTorneio, TCG
from app.services.ConquistaService import recalcular_conquistas_jogador

# Valores conhecidos do atributo `outcome` de <match> no .tdf — mapeamento
# confirmado pelo time (ver docs/IMPORTACAO.md). Qualquer valor de outcome
# fora deste conjunto trava a importação com uma mensagem clara em vez de
# arriscar registrar um resultado errado (bug real corrigido aqui: a versão
# antiga tratava qualquer `outcome != 2` como "jogador 1 venceu", então um
# empate — outcome 3 — virava, por engano, uma vitória do jogador 1).
OUTCOME_JOGADOR1_VENCEU = 1
OUTCOME_JOGADOR2_VENCEU = 2
OUTCOME_EMPATE = 3
OUTCOME_BYE = 5


def _erro_importacao(mensagem: str) -> HTTPException:
    """Toda falha de importação (bloco/atributo ausente, valor num formato
    inesperado, código não mapeado, etc.) precisa passar por aqui — nunca
    deixar uma exceção "crua" do Python (AttributeError, KeyError, TypeError)
    subir sem tratamento: sem isso, o FastAPI devolve um 500 sem `detail`
    nenhum, e o toast do frontend mostra só uma mensagem genérica, sem dar
    ao usuário nada que ele consiga repassar pro time de desenvolvimento
    (ver docs/IMPORTACAO.md). Importação de torneio é a funcionalidade
    principal da plataforma — qualquer problema aqui precisa de uma
    mensagem clara, não um erro mudo."""
    return TopDeckedException.bad_request(
        f"{mensagem} Avise o time de desenvolvimento sobre esse problema, de preferência "
        "junto com o arquivo que você tentou importar."
    )


def _exigir_elemento(pai: ET.Element, tag: str, contexto: str) -> ET.Element:
    elemento = pai.find(tag)
    if elemento is None:
        raise _erro_importacao(
            f"O bloco '{tag}' não foi encontrado {contexto} — esse arquivo pode ter um formato "
            "de exportação diferente do que a plataforma espera."
        )
    return elemento


def _exigir_atributo(elemento: ET.Element, atributo: str, contexto: str) -> str:
    valor = elemento.get(atributo)
    if valor is None:
        raise _erro_importacao(
            f"O atributo '{atributo}' não foi encontrado {contexto} — esse arquivo pode ter um "
            "formato de exportação diferente do que a plataforma espera."
        )
    return valor


def _int_obrigatorio(valor: str | None, descricao: str) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise _erro_importacao(f"{descricao} está ausente ou não é um número válido no arquivo.")


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

    # Torneio importado já nasce FINALIZADO, então nunca pode ficar sem data
    # real — o .tdf normalmente traz timestamps de partida suficientes pra
    # calculá-la, mas um arquivo sem rodadas (ou sem timestamp em nenhuma
    # partida) deixaria inicio_real/fim_real nulos sem este fallback.
    torneio.inicio_real = inicio_real or agora_brasil()
    torneio.fim_real = fim_real or agora_brasil()
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

    id = dados.findtext("id", default="")
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


def _data_nascimento_importada(birthdate_str: str | None):
    """`parse_data` já espera exatamente o formato MM/DD/YYYY usado por
    <birthdate> (mesmo formato de <startdate>) — mas, diferente da data de
    início do torneio, uma data de nascimento ausente/mal formada num
    participante não deveria derrubar a importação inteira, então qualquer
    erro de parsing aqui é silenciado (fica None). `parse_data` levanta
    `HTTPException` (via `TopDeckedException.bad_request`, que NÃO é uma
    classe de exceção de verdade — só um factory de `HTTPException` — por
    isso o catch é em `HTTPException`, não em `TopDeckedException`: um
    `except TopDeckedException` aqui derrubaria a importação inteira com um
    TypeError, o oposto do que este código quer)."""
    if not birthdate_str:
        return None
    try:
        return parse_data(birthdate_str)
    except HTTPException:
        return None


def _criar_relacao_jogador_torneio(xml: ET.Element, torneio: Torneio, session: SessionDep):
    jogadores_dict = {}

    dados = xml.find("players")

    if dados is None:
        return jogadores_dict

    for jogador in dados.findall("player"):
        gameid_importado = jogador.attrib.get("userid")
        if not gameid_importado:
            raise _erro_importacao(
                "Um jogador do arquivo não tem ID ('userid') — não é possível identificá-lo."
            )
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
                # Só preenchida na criação — se o JogadorCriado já existir
                # (import repetido, ou já veio de outra loja/torneio), o
                # valor atual é mantido como está, mesmo que seja None.
                data_nascimento=_data_nascimento_importada(jogador.findtext("birthdate")),
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
    pods = _exigir_elemento(xml, "pods", "no arquivo").findall("pod")
    rodadas = []
    for pod in pods:
        rounds_el = _exigir_elemento(pod, "rounds", "dentro de um 'pod' do arquivo")
        rodadas.extend(rounds_el.findall("round"))

    inicio_real = _calcular_inicio_real(rodadas)
    fim_real = _calcular_fim_real(rodadas)

    for rodada in rodadas:
        num_rodada = _int_obrigatorio(rodada.get("number"), "O número de uma rodada")
        partidas = _exigir_elemento(rodada, "matches", f"na rodada {num_rodada} do arquivo")

        _importar_partidas(partidas, jogadores_dict, torneio_id, num_rodada, session)

    return inicio_real, fim_real


def _timestamps_da_rodada(rodadas: list[ET.Element], numero: int) -> list[datetime]:
    stamps = []
    for rodada in rodadas:
        if _int_obrigatorio(rodada.get("number"), "O número de uma rodada") != numero:
            continue
        matches_el = _exigir_elemento(rodada, "matches", f"na rodada {numero} do arquivo")
        for match in matches_el.findall("match"):
            ts = match.findtext("timestamp")
            if ts:
                stamps.append(parse_datetime(ts))
    return stamps


def _calcular_inicio_real(rodadas: list[ET.Element]) -> datetime | None:
    """Menor timestamp de partida dentro da primeira rodada — usado como
    aproximação de quando o torneio de fato começou (ver docs/CONQUISTAS.md)."""
    if not rodadas:
        return None
    primeira_rodada_num = min(_int_obrigatorio(r.get("number"), "O número de uma rodada") for r in rodadas)
    stamps = _timestamps_da_rodada(rodadas, primeira_rodada_num)
    return min(stamps) if stamps else None


def _calcular_fim_real(rodadas: list[ET.Element]) -> datetime | None:
    """Maior timestamp de partida dentro da última rodada — usado como
    aproximação de quando o torneio de fato terminou (ver docs/CONQUISTAS.md).
    Espelha _calcular_inicio_real (menor timestamp da primeira rodada)."""
    if not rodadas:
        return None
    ultima_rodada_num = max(_int_obrigatorio(r.get("number"), "O número de uma rodada") for r in rodadas)
    stamps = _timestamps_da_rodada(rodadas, ultima_rodada_num)
    return max(stamps) if stamps else None


def _importar_partidas(partidas: ET.Element, jogadores_dict: dict, torneio_id: str, num_rodada: int, session: SessionDep):
    partidas_criadas = []
    for partida in partidas.findall("match"):
        jogador1_id = None
        jogador2_id = None

        jogador = partida.find("player")
        if jogador is not None:
            jogador1_id = _exigir_atributo(
                jogador, "userid", f"de um jogador (partida com bye) da rodada {num_rodada}")
        else:
            player1_el = _exigir_elemento(partida, "player1", f"numa partida da rodada {num_rodada}")
            player2_el = _exigir_elemento(partida, "player2", f"numa partida da rodada {num_rodada}")
            jogador1_id = _exigir_atributo(player1_el, "userid", f"do jogador 1 de uma partida da rodada {num_rodada}")
            jogador2_id = _exigir_atributo(player2_el, "userid", f"do jogador 2 de uma partida da rodada {num_rodada}")

        outcome_str = partida.get("outcome")
        if outcome_str is None:
            raise _erro_importacao(
                f"Uma partida da rodada {num_rodada} não tem o resultado ('outcome') no arquivo — "
                "não é possível saber quem venceu."
            )
        outcome = _int_obrigatorio(outcome_str, f"O resultado ('outcome') de uma partida da rodada {num_rodada}")

        # Mapeamento confirmado pelo time (OUTCOME_* no topo do arquivo):
        # 1 = jogador 1 venceu, 2 = jogador 2 venceu, 3 = empate, 5 = bye
        # (jogador 1 "vence" automaticamente, sem oponente real). Qualquer
        # código fora desse conjunto precisa ser investigado e mapeado
        # explicitamente antes de confiar nele; até lá, é mais seguro travar
        # a importação com um aviso claro do que silenciosamente registrar
        # um resultado errado (ver docs/IMPORTACAO.md).
        if outcome == OUTCOME_JOGADOR1_VENCEU:
            vencedor = jogador1_id
        elif outcome == OUTCOME_JOGADOR2_VENCEU:
            vencedor = jogador2_id
        elif outcome == OUTCOME_EMPATE:
            vencedor = None
        elif outcome == OUTCOME_BYE:
            vencedor = jogador1_id
        else:
            raise _erro_importacao(
                f"O resultado (outcome={outcome}) de uma partida da rodada {num_rodada} não é um "
                "valor reconhecido pela plataforma (esperado 1, 2, 3 ou 5)."
            )

        mesa = _int_obrigatorio(
            partida.findtext("tablenumber"), f"O número da mesa de uma partida da rodada {num_rodada}")

        timestamp_str = partida.findtext("timestamp")
        data_de_inicio = parse_datetime(timestamp_str)

        # Partida "bye" (rodada ímpar): o XML só traz um único <player>, então
        # jogador2_id/vencedor podem ser None aqui — não são gameids reais,
        # então não estão (e não devem estar) em jogadores_dict.
        try:
            jogador1_link_id = jogadores_dict[jogador1_id]
            jogador2_link_id = jogadores_dict[jogador2_id] if jogador2_id is not None else None
            vencedor_link_id = jogadores_dict[vencedor] if vencedor is not None else None
        except KeyError as chave_ausente:
            raise _erro_importacao(
                f"O jogador de ID '{chave_ausente.args[0]}' aparece numa partida da rodada "
                f"{num_rodada}, mas não está na lista de jogadores do torneio — o arquivo pode "
                "estar incompleto ou corrompido."
            )

        partida_criada = Rodada(
            jogador1_id=jogador1_link_id,
            jogador2_id=jogador2_link_id,
            vencedor_id=vencedor_link_id,
            torneio_id=torneio_id,
            num_rodada=num_rodada,
            mesa=mesa,
            data_de_inicio=data_de_inicio,
            finalizada=True
        )
        session.add(partida_criada)
        session.commit()
        session.refresh(partida_criada)
        partidas_criadas.append(partida_criada)

    return partidas_criadas
