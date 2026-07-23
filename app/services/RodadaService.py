from app.core.db import SessionDep
from app.models import Torneio, Rodada, JogadorTorneioLink, Jogador
from sqlmodel import select
from app.services.ComposicaoService import garantir_composicao_partida
from app.services.JogadorService import retornar_vde_jogador
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.Enums import TipoParticipanteTorneio


def _info_participante(session: SessionDep, participante: JogadorTorneioLink, vde: dict) -> dict:
    jogador_id = participante.jogador_criado.jogador_id if participante.jogador_criado else None
    jogador_real = session.get(Jogador, jogador_id) if jogador_id else None
    return {
        "jogador_id": jogador_id,
        "usuario_id": jogador_real.usuario_id if jogador_real else None,
        "jogador_nome": jogador_real.nome if jogador_real else participante.apelido,
        **vde,
    }


def nova_rodada(session: SessionDep, torneio: Torneio):
    jogadores = session.exec(select(JogadorTorneioLink)
                             .where(
                                 (JogadorTorneioLink.torneio_id == torneio.id) &
                                 (JogadorTorneioLink.tipo.in_([
                                     TipoParticipanteTorneio.JOGADOR,
                                     TipoParticipanteTorneio.JOGADOR_E_JUIZ,
                                 ]))
                             )).all()

    jogadores = sorted(jogadores, key=lambda j: (
        j.pontuacao, j.jogador_criado_id), reverse=True)
    mesa_livre = 1
    rodada_atual = torneio.rodada_atual + 1

    jogando = {}
    result = {}
    for i, jogador in enumerate(jogadores):
        adversario = None
        if jogando.get(jogador.id, False):
            continue

        for pos_adversario in jogadores[i+1:]:
            if jogando.get(pos_adversario.id, False):
                continue

            ja_jogaram = session.exec(
                select(Rodada).where(
                    ((Rodada.jogador1_id == jogador.id) &
                     (Rodada.jogador2_id == pos_adversario.id))
                    |
                    ((Rodada.jogador1_id == pos_adversario.id) &
                     (Rodada.jogador2_id == jogador.id))
                )
            ).first()

            if ja_jogaram:
                continue

            adversario = pos_adversario
            break

        nova_rodada = Rodada(
            jogador1_id=jogador.id,
            jogador2_id=adversario.id if adversario else None,
            torneio_id=torneio.id,
            loja_id=torneio.loja_id,
            num_rodada=rodada_atual,
            mesa=mesa_livre,
            data_de_inicio=data_agora_brasil(),
            finalizada=False
        )
        session.add(nova_rodada)
        session.flush()

        # Cada lado da rodada (link de participação, não a Jogador ainda —
        # essa reatribuição só acontece nas linhas abaixo) ganha sua própria
        # ComposicaoPartida (mesmo id reaproveitado partida a partida pra
        # TCG/VGC, id novo a cada rodada só pra Pokémon GO — ver
        # ComposicaoService.garantir_composicao_partida).
        garantir_composicao_partida(session, nova_rodada.id, jogador, torneio.jogo)
        if adversario:
            garantir_composicao_partida(session, nova_rodada.id, adversario, torneio.jogo)

        jogando[jogador.id] = True
        jogador_vde = retornar_vde_jogador(
            session, jogador.jogador_criado.jogador_id, torneio)

        adversario_info = {}
        if adversario:
            jogando[adversario.id] = True
            adversario_vde = retornar_vde_jogador(
                session, adversario.jogador_criado.jogador_id, torneio)
            adversario_info = _info_participante(session, adversario, adversario_vde)

        result[str(nova_rodada.id)] = [
            {
                "mesa": mesa_livre,
                "jogador1": _info_participante(session, jogador, jogador_vde),
                "jogador2": adversario_info,
            }
        ]

        mesa_livre += 1

    torneio.rodada_atual = rodada_atual
    session.add(torneio)
    return result
