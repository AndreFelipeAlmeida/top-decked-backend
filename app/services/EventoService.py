from sqlmodel import select
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.dependencies import definir_tenant_sessao
from app.models import (
    Evento,
    Jogador,
    JogadorCriado,
    JogadorTorneioLink,
    LojaJogadorLink,
    LojaJogadorOrganizadorTCG,
    ParticipanteEvento,
    PontosManualEvento,
    Torneio,
)
from app.utils.datetimeUtil import data_agora_brasil
from app.utils.Enums import StatusTorneio, TipoParticipanteTorneio, TipoRegraPontuacaoEvento
from app.utils.TorneioDataUtil import data_efetiva_torneio, momento_efetivo_torneio


def verificar_permissao_evento(session: SessionDep, evento: Evento, usuario: TokenData) -> None:
    if usuario.tipo == "loja":
        if evento.loja_id != usuario.id:
            raise TopDeckedException.forbidden()
        definir_tenant_sessao(session, evento.loja_id)
        return

    if usuario.tipo == "jogador":
        link = session.exec(
            select(LojaJogadorLink).where(
                (LojaJogadorLink.loja_id == evento.loja_id) &
                (LojaJogadorLink.jogador_id == usuario.id)
            )
        ).first()

        if not link:
            raise TopDeckedException.forbidden("Jogador não pertence a esta loja")

        organiza_tcg = session.exec(
            select(LojaJogadorOrganizadorTCG).where(
                (LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id) &
                (LojaJogadorOrganizadorTCG.tcg == evento.tcg)
            )
        ).first()

        if not organiza_tcg:
            raise TopDeckedException.forbidden(
                "Jogador não possui permissão para gerenciar eventos deste TCG nesta loja"
            )
        definir_tenant_sessao(session, evento.loja_id)
        return

    raise TopDeckedException.forbidden()


def _composicao_pontos_automaticos(session: SessionDep, evento: Evento, jogador_criado_id: int) -> list[dict]:
    """Quebra os pontos automáticos do jogador neste evento em pedaços por
    motivo (um pedaço por regra que rendeu pontos em cada torneio finalizado
    dentro do período), em ordem cronológica dos torneios. Usado tanto pro
    total (`calcular_pontos_automaticos`) quanto pro tooltip da trilha de
    pontos de `ParticipanteCartela`. Nunca armazenado — recalculado a cada
    consulta. Quem é só Juiz (JogadorTorneioLink.tipo == JUIZ) não pontua
    automaticamente aqui — não é jogador de verdade no torneio; ainda pode
    receber pontos manuais (Outros Motivos). JOGADOR_E_JUIZ pontua
    normalmente pela parte de Jogador."""
    pontos_por_tipo: dict[TipoRegraPontuacaoEvento, float] = {}
    for regra in evento.regras:
        pontos_por_tipo[regra.tipo] = pontos_por_tipo.get(regra.tipo, 0) + regra.pontos

    if not pontos_por_tipo:
        return []

    # Sem filtro de data na query: pra torneios FINALIZADOS o que importa é
    # a data efetiva (real, não a planejada — ver TorneioDataUtil), então o
    # recorte pelo período do evento é feito em Python logo abaixo, depois
    # de calcular essa data.
    candidatos = session.exec(
        select(Torneio)
        .where(
            (Torneio.loja_id == evento.loja_id) &
            (Torneio.jogo == evento.tcg) &
            (Torneio.status == StatusTorneio.FINALIZADO) &
            Torneio.conta_em_eventos
        )
    ).all()

    torneios = sorted(
        (t for t in candidatos if evento.data_inicio <= data_efetiva_torneio(t) <= evento.data_fim),
        key=momento_efetivo_torneio,
    )

    composicao: list[dict] = []
    for torneio in torneios:
        link = session.exec(
            select(JogadorTorneioLink).where(
                (JogadorTorneioLink.torneio_id == torneio.id) &
                (JogadorTorneioLink.jogador_criado_id == jogador_criado_id) &
                (JogadorTorneioLink.tipo.in_([
                    TipoParticipanteTorneio.JOGADOR,
                    TipoParticipanteTorneio.JOGADOR_E_JUIZ,
                ]))
            )
        ).first()

        if not link:
            continue

        momento = momento_efetivo_torneio(torneio)
        if TipoRegraPontuacaoEvento.PARTICIPACAO in pontos_por_tipo:
            composicao.append({"motivo": "Participação", "pontos": pontos_por_tipo[TipoRegraPontuacaoEvento.PARTICIPACAO], "momento": momento})
        if TipoRegraPontuacaoEvento.VITORIA in pontos_por_tipo and link.vitorias:
            composicao.append({"motivo": "Vitória", "pontos": pontos_por_tipo[TipoRegraPontuacaoEvento.VITORIA] * link.vitorias, "momento": momento})
        if TipoRegraPontuacaoEvento.DERROTA in pontos_por_tipo and link.derrotas:
            composicao.append({"motivo": "Derrota", "pontos": pontos_por_tipo[TipoRegraPontuacaoEvento.DERROTA] * link.derrotas, "momento": momento})
        if TipoRegraPontuacaoEvento.EMPATE in pontos_por_tipo and link.empates:
            composicao.append({"motivo": "Empate", "pontos": pontos_por_tipo[TipoRegraPontuacaoEvento.EMPATE] * link.empates, "momento": momento})

    return composicao


def calcular_pontos_automaticos(session: SessionDep, evento: Evento, jogador_criado_id: int) -> float:
    return sum(chunk["pontos"] for chunk in _composicao_pontos_automaticos(session, evento, jogador_criado_id))


def calcular_pontos_manuais(session: SessionDep, evento_id: int, jogador_criado_id: int) -> float:
    pontos = session.exec(
        select(PontosManualEvento.pontos).where(
            (PontosManualEvento.evento_id == evento_id) &
            (PontosManualEvento.jogador_criado_id == jogador_criado_id)
        )
    ).all()
    return sum(pontos)


def _composicao_pontos_manuais(session: SessionDep, evento_id: int, jogador_criado_id: int) -> list[dict]:
    registros = session.exec(
        select(PontosManualEvento)
        .where(
            (PontosManualEvento.evento_id == evento_id) &
            (PontosManualEvento.jogador_criado_id == jogador_criado_id)
        )
        .order_by(PontosManualEvento.criado_em)
    ).all()
    return [
        {"motivo": registro.descricao, "pontos": registro.pontos, "momento": registro.criado_em}
        for registro in registros
    ]


def retornar_participante_completo(session: SessionDep, evento: Evento, participante: ParticipanteEvento) -> dict:
    jogador_criado = participante.jogador_criado
    composicao_automatica = _composicao_pontos_automaticos(session, evento, participante.jogador_criado_id)
    composicao_manual = _composicao_pontos_manuais(session, evento.id, participante.jogador_criado_id)
    pontos_automaticos = sum(chunk["pontos"] for chunk in composicao_automatica)
    pontos_manuais = sum(chunk["pontos"] for chunk in composicao_manual)

    # Foto de perfil vem da conta real (Jogador -> Usuario), quando o
    # participante tiver uma vinculada — registros avulsos (sem conta) não
    # têm foto.
    foto = None
    if jogador_criado and jogador_criado.jogador and jogador_criado.jogador.usuario:
        foto = jogador_criado.jogador.usuario.foto

    return {
        "id": participante.id,
        "jogador_criado_id": participante.jogador_criado_id,
        "apelido": jogador_criado.apelido if jogador_criado else None,
        "game_id": jogador_criado.game_id if jogador_criado else None,
        "foto": foto,
        "pontos_automaticos": pontos_automaticos,
        "pontos_manuais": pontos_manuais,
        "pontos_total": pontos_automaticos + pontos_manuais,
        # Ordem em que os pontos "preenchem" a trilha de carimbos do
        # participante: estritamente cronológica pelo momento em que cada
        # pedaço foi ganho (torneio finalizado ou ponto manual concedido),
        # intercalando automáticos e manuais — não é "automáticos primeiro,
        # manuais depois". Só pra exibir o motivo no tooltip de cada
        # carimbo, não afeta o total.
        "composicao_pontos": sorted(composicao_automatica + composicao_manual, key=lambda chunk: chunk["momento"]),
    }


def retornar_evento_completo(session: SessionDep, evento: Evento) -> dict:
    hoje = data_agora_brasil()
    if hoje < evento.data_inicio:
        status = "AGENDADO"
    elif hoje > evento.data_fim:
        status = "ENCERRADO"
    else:
        status = "ATIVO"

    return {
        "id": evento.id,
        "loja_id": evento.loja_id,
        "loja": evento.loja,
        "tcg": evento.tcg,
        "nome": evento.nome,
        "descricao": evento.descricao,
        "data_inicio": evento.data_inicio,
        "data_fim": evento.data_fim,
        "status": status,
        "metas": sorted(evento.metas, key=lambda m: m.pontos_necessarios),
        "regras": evento.regras,
        "regras_manuais": evento.regras_manuais,
        "participantes": [
            retornar_participante_completo(session, evento, participante)
            for participante in evento.participantes
        ],
    }


def listar_jogadores_disponiveis(session: SessionDep, evento: Evento) -> list[JogadorCriado]:
    """Jogadores selecionáveis pra adicionar como participante do evento:
    contas cadastradas nesta loja, organizadores da loja, registros avulsos
    (sem conta vinculada) que já jogaram algum torneio desta loja, mais quem
    já é participante."""
    registrados_na_loja = session.exec(
        select(JogadorCriado)
        .join(Jogador, Jogador.id == JogadorCriado.jogador_id)
        .join(LojaJogadorLink, LojaJogadorLink.jogador_id == Jogador.id)
        .where(
            (LojaJogadorLink.loja_id == evento.loja_id) &
            (JogadorCriado.tcg == evento.tcg)
        )
    ).all()

    ja_jogou_na_loja = session.exec(
        select(JogadorCriado)
        .join(JogadorTorneioLink, JogadorTorneioLink.jogador_criado_id == JogadorCriado.id)
        .join(Torneio, Torneio.id == JogadorTorneioLink.torneio_id)
        .where(
            (Torneio.loja_id == evento.loja_id) &
            (JogadorCriado.tcg == evento.tcg)
        )
    ).all()

    por_id = {jc.id: jc for jc in registrados_na_loja}
    for jc in ja_jogou_na_loja:
        por_id[jc.id] = jc

    ja_participantes_ids = [p.jogador_criado_id for p in evento.participantes]
    if ja_participantes_ids:
        ja_participantes = session.exec(
            select(JogadorCriado).where(JogadorCriado.id.in_(ja_participantes_ids))
        ).all()
        for jc in ja_participantes:
            por_id[jc.id] = jc

    return sorted(por_id.values(), key=lambda jc: (jc.apelido or jc.game_id or "").lower())


def adicionar_participante(session: SessionDep, evento: Evento, jogador_criado_id: int) -> ParticipanteEvento:
    jogador_criado = session.get(JogadorCriado, jogador_criado_id)
    if not jogador_criado:
        raise TopDeckedException.not_found("Jogador não encontrado")
    if jogador_criado.tcg != evento.tcg:
        raise TopDeckedException.bad_request(
            "Esse jogador não tem cadastro para o jogo deste evento")

    ja_existe = session.exec(
        select(ParticipanteEvento).where(
            (ParticipanteEvento.evento_id == evento.id) &
            (ParticipanteEvento.jogador_criado_id == jogador_criado_id)
        )
    ).first()
    if ja_existe:
        raise TopDeckedException.bad_request("Esse jogador já é participante deste evento")

    participante = ParticipanteEvento(evento_id=evento.id, jogador_criado_id=jogador_criado_id)
    session.add(participante)
    session.commit()
    session.refresh(participante)
    return participante
