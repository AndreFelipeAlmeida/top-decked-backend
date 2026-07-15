from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select, func
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.models import Rodada, Torneio, Jogador, JogadorCriado, JogadorTorneioLink, TipoJogador, LojaJogadorLink, LojaJogadorOrganizadorTCG, PontuacaoExtra
from app.utils.Enums import TCG, TipoParticipanteTorneio
from app.utils.CategoriaUtil import encontrar_temporada_do_torneio, calcular_categoria_na_temporada

# Jogos com formato suíço, onde o desempate por OMW%/OOMW% (ver
# calcular_desempate_suico) faz sentido — outros TCGs (Yu-Gi-Oh!, Magic) usam
# outros formatos de torneio e não entram aqui por enquanto.
JOGOS_FORMATO_SUICO = (TCG.POKEMON, TCG.POKEMON_VGC)


def verificar_permissao_gerenciar_torneio(session: SessionDep, torneio: Torneio, usuario: TokenData):
    """Autoriza tanto a loja dona do torneio quanto um jogador que organiza o
    TCG do torneio nessa loja (ver docs/DIVIDA_TECNICA.md) a gerenciá-lo
    (editar, importar resultados, ajustar/recalcular pontuação)."""
    if usuario.tipo == "loja":
        if torneio.loja_id != usuario.id:
            raise TopDeckedException.forbidden()
        return

    if usuario.tipo == "jogador":
        link = session.exec(
            select(LojaJogadorLink)
            .where(
                (LojaJogadorLink.loja_id == torneio.loja_id) &
                (LojaJogadorLink.jogador_id == usuario.id)
            )
        ).first()

        if not link:
            raise TopDeckedException.forbidden(
                "Jogador não pertence a esta loja"
            )

        organiza_tcg = session.exec(
            select(LojaJogadorOrganizadorTCG)
            .where(
                (LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id) &
                (LojaJogadorOrganizadorTCG.tcg == torneio.jogo)
            )
        ).first()

        if not organiza_tcg:
            raise TopDeckedException.forbidden(
                "Jogador não possui permissão para gerenciar torneios deste TCG nesta loja"
            )
        return

    raise TopDeckedException.forbidden()


def calcular_categoria_do_link(session: SessionDep, torneio: Torneio, link: JogadorTorneioLink) -> str | None:
    """Categoria (Junior/Senior/Master) do jogador NESTE torneio — sempre
    calculada na hora a partir da Temporada vigente (pela data do torneio),
    nunca armazenada (ver docs/TEMPORADAS.md). Data de nascimento: usa a do
    JogadorCriado; se ele não tiver uma (ex.: veio de um import antigo, sem
    <birthdate>), cai pra data de nascimento da conta real vinculada
    (Jogador.data_nascimento), se houver uma. Sem nenhuma das duas, ou sem
    Temporada cadastrada pro jogo/período do torneio, o jogador não entra na
    categorização (None)."""
    if not link.jogador_criado:
        return None

    data_nascimento = link.jogador_criado.data_nascimento
    if not data_nascimento and link.jogador_criado.jogador:
        data_nascimento = link.jogador_criado.jogador.data_nascimento

    if not data_nascimento:
        return None

    temporada = encontrar_temporada_do_torneio(session, torneio)
    if not temporada:
        return None

    return calcular_categoria_na_temporada(data_nascimento, temporada)


def retornar_link_completo(session: SessionDep, torneio: Torneio, link: JogadorTorneioLink) -> dict:
    composicao_representacao = None
    if link.composicao_representacao:
        composicao_representacao = {
            "id": link.composicao_representacao.id,
            "tcg": link.composicao_representacao.tcg,
            "nome": link.composicao_representacao.nome,
            "unidades": [
                {
                    "id": p.unidade.id,
                    "tcg": p.unidade.tcg,
                    "external_id": p.unidade.external_id,
                    "nome": p.unidade.nome,
                }
                for p in link.composicao_representacao.unidades
            ],
        }

    return {
        "id": link.id,
        "jogador_criado_id": link.jogador_criado_id,
        "jogador_id": link.jogador_criado.jogador_id if link.jogador_criado else None,
        "game_id": link.jogador_criado.game_id if link.jogador_criado else None,
        "apelido": link.apelido,
        "tipo": link.tipo,
        "regra_extra_id": link.regra_extra_id,
        "pontuacao": link.pontuacao,
        "pontuacao_com_regras": link.pontuacao_com_regras,
        "composicao_representacao_id": link.composicao_representacao_id,
        "composicao_representacao": composicao_representacao,
        "composicao_unidades": [
            {
                "unidade_catalogo_id": dc.unidade_catalogo_id,
                "quantidade": dc.quantidade,
                "unidade": {
                    "id": dc.unidade.id,
                    "tcg": dc.unidade.tcg,
                    "external_id": dc.unidade.external_id,
                    "nome": dc.unidade.nome,
                },
            }
            for dc in link.composicao_unidades
        ],
        "vitorias": link.vitorias,
        "derrotas": link.derrotas,
        "empates": link.empates,
        "byes": link.byes,
        "porcentagem_vitorias_oponentes": link.porcentagem_vitorias_oponentes,
        "porcentagem_vitorias_oponentes_oponentes": link.porcentagem_vitorias_oponentes_oponentes,
        "categoria": calcular_categoria_do_link(session, torneio, link),
    }


def salvar_link_ou_conflito(session: SessionDep, link: JogadorTorneioLink, mensagem: str) -> None:
    """Persiste um JogadorTorneioLink novo protegido contra corrida entre
    duas requisições concorrentes que passam as duas pela checagem de
    duplicidade em Python antes de uma delas inserir — quem perder a corrida
    esbarra na UniqueConstraint uix_jogador_torneio_tipo do banco e recebe um
    409 amigável em vez de um 500."""
    session.add(link)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise TopDeckedException.conflict(mensagem)


def adicionar_juiz(session: SessionDep, torneio: Torneio, jogador_criado_id: int) -> JogadorTorneioLink:
    """Vincula um jogador ao torneio como Juiz, oficializando o papel antes
    de ele poder receber Pontuação Extra com motivo Juiz (ver
    PontuacaoExtraService.criar_pontuacao_extra, que agora exige esse vínculo
    já existir). Um jogador só tem UMA linha por torneio (fonte única de
    verdade): se ele já é JOGADOR aqui, isso é um upsert — vira
    JOGADOR_E_JUIZ em vez de criar uma segunda linha."""
    jogador_criado = session.get(JogadorCriado, jogador_criado_id)
    if not jogador_criado:
        raise TopDeckedException.not_found("Jogador não encontrado")
    if jogador_criado.tcg != torneio.jogo:
        raise TopDeckedException.bad_request(
            "Esse jogador não tem cadastro para o jogo deste torneio")

    link = session.exec(
        select(JogadorTorneioLink).where(
            (JogadorTorneioLink.torneio_id == torneio.id) &
            (JogadorTorneioLink.jogador_criado_id == jogador_criado_id)
        )
    ).first()

    if link:
        if link.tipo in (TipoParticipanteTorneio.JUIZ, TipoParticipanteTorneio.JOGADOR_E_JUIZ):
            raise TopDeckedException.bad_request("Este jogador já está cadastrado como Juiz neste torneio")
        link.tipo = TipoParticipanteTorneio.JOGADOR_E_JUIZ
        session.add(link)
        session.commit()
        session.refresh(link)
        return link

    link = JogadorTorneioLink(
        torneio_id=torneio.id,
        loja_id=torneio.loja_id,
        jogador_criado_id=jogador_criado_id,
        apelido=jogador_criado.apelido or jogador_criado.game_id,
        tipo=TipoParticipanteTorneio.JUIZ,
    )
    salvar_link_ou_conflito(session, link, "Este jogador já está cadastrado como Juiz neste torneio")
    session.commit()
    session.refresh(link)
    return link


def remover_juiz(session: SessionDep, torneio: Torneio, link_id: int) -> None:
    """Remove o papel de Juiz. Se o jogador também é JOGADOR (tipo
    JOGADOR_E_JUIZ), é um downgrade — a linha continua existindo como só
    JOGADOR. Se Juiz era o único papel dele, a linha é deletada de vez."""
    link = session.get(JogadorTorneioLink, link_id)
    if not link or link.torneio_id != torneio.id:
        raise TopDeckedException.not_found("Vínculo não encontrado")
    if link.tipo not in (TipoParticipanteTorneio.JUIZ, TipoParticipanteTorneio.JOGADOR_E_JUIZ):
        raise TopDeckedException.bad_request("Este vínculo não é de um Juiz")

    if link.tipo == TipoParticipanteTorneio.JOGADOR_E_JUIZ:
        link.tipo = TipoParticipanteTorneio.JOGADOR
        session.add(link)
        session.commit()
        return

    session.delete(link)
    session.commit()


def retornar_torneio_completo(session: SessionDep, torneio: Torneio):
    torneio_dict = torneio.model_dump()

    torneio_dict["loja"] = torneio.loja
    torneio_dict["jogadores"] = [
        retornar_link_completo(session, torneio, link)
        for link in torneio.jogadores
    ]

    torneio_dict["rodadas"] = [
        {
            "id": rodada.id,
            "jogador1_id": rodada.jogador1_id,
            "jogador2_id": rodada.jogador2_id,
            # Bug corrigido aqui (ver docs/DIVIDA_TECNICA.md): a chave era
            # "vencedor" (o relacionamento) em vez de "vencedor_id" (a coluna
            # escalar que TorneioPublico/RodadaPublico de fato esperam) — o
            # vencedor da rodada nunca aparecia na resposta da API, sempre
            # serializando como null independente do resultado real.
            "vencedor_id": rodada.vencedor_id,
            "num_rodada": rodada.num_rodada,
            "mesa": rodada.mesa,
            "data_de_inicio": rodada.data_de_inicio,
            "finalizada": rodada.finalizada,
        }
        for rodada in torneio.rodadas
    ]


    return torneio_dict


def regras_extras_atuais(torneio: Torneio) -> dict:
    """Dict {link_id (str): regra_extra_id} com as regras extras já
    atribuídas por jogador neste torneio agora. Usado por chamadores de
    editar_torneio_regras que não estão mexendo em regra extra nenhuma (ex.:
    salvar o nome/data do torneio, iniciar o torneio) e só querem preservar o
    que já existe — sem isso, o "else: None" de editar_torneio_regras
    apagaria a regra extra de todo mundo a cada chamada (ver
    docs/REGRA_EXTRA.md)."""
    return {
        str(jt.id): jt.regra_extra_id
        for jt in torneio.jogadores
        if jt.regra_extra_id is not None
    }


def editar_torneio_regras(session: SessionDep, torneio: Torneio, regra_basica: int, regras_adicionais: dict):
    if regra_basica:
        torneio.regra_basica_id = regra_basica

    # pontuacao_com_regras é sempre recalculada do zero aqui (rodadas somam
    # em cima logo abaixo, em calcular_pontuacao) — Pontuação Extra
    # (PontuacaoExtra, ver docs/PONTUACAO_EXTRA.md) não é uma rodada, então
    # precisa ser resomada explicitamente como parte da base, junto de
    # pontuacao_de_participacao, senão qualquer reset (finalizar rodada,
    # trocar regra, recalcular) apagaria pontos extras já dados.
    pontos_extras_por_jogador = dict(
        session.exec(
            select(PontuacaoExtra.jogador_criado_id, func.sum(PontuacaoExtra.pontos))
            .where(PontuacaoExtra.torneio_id == torneio.id)
            .group_by(PontuacaoExtra.jogador_criado_id)
        ).all()
    )

    for jogador in torneio.jogadores:
        jogador.pontuacao = 0
        jogador.pontuacao_com_regras = (
            torneio.pontuacao_de_participacao
            + pontos_extras_por_jogador.get(jogador.jogador_criado_id, 0)
        )
        jogador_id = jogador.id

        if regras_adicionais and str(jogador_id) in regras_adicionais.keys():
            jogador.regra_extra_id = regras_adicionais[str(jogador_id)]
        else:
            # Sem entrada em regras_adicionais = sem regra extra (None) — a
            # regra básica do torneio já se aplica a todo mundo sozinha, uma
            # regra extra é sempre um ajuste OPCIONAL por cima dela (ver
            # docs/REGRA_EXTRA.md), nunca um valor que "falta preencher".
            jogador.regra_extra_id = None
        session.add(jogador)

    return torneio


def calcular_pontuacao(session: SessionDep, torneio: Torneio):
    regra_basica = torneio.regra_basica

    for rodada in torneio.rodadas:
        calcular_pontuacao_rodada(session,rodada,regra_basica)

    calcular_desempate_suico(session, torneio)


def calcular_desempate_suico(session: SessionDep, torneio: Torneio) -> None:
    """Recalcula, para cada participação (JogadorTorneioLink) deste torneio,
    os contadores de vitórias/derrotas/empates/byes e o desempate suíço
    padrão: OMW% (média da taxa de vitória dos adversários reais — byes não
    contam como adversário de ninguém) e OOMW% (média do OMW% dos
    adversários), usado quando o OMW% empata. Ver docs/RANKING.md.

    Só roda para jogos de formato suíço (JOGOS_FORMATO_SUICO) — outros TCGs
    ficam com os contadores zerados e as porcentagens em None.
    """
    if torneio.jogo not in JOGOS_FORMATO_SUICO:
        return

    links = torneio.jogadores
    por_link: dict[int, dict] = {}

    for link in links:
        vitorias = derrotas = empates = byes = 0
        oponentes_ids: list[int] = []

        for rodada in torneio.rodadas:
            if rodada.jogador1_id != link.id and rodada.jogador2_id != link.id:
                continue

            eh_bye = rodada.jogador1_id is None or rodada.jogador2_id is None
            if eh_bye:
                byes += 1
                continue

            oponente_id = rodada.jogador2_id if rodada.jogador1_id == link.id else rodada.jogador1_id
            oponentes_ids.append(oponente_id)

            if rodada.vencedor_id == link.id:
                vitorias += 1
            elif rodada.vencedor_id == oponente_id:
                derrotas += 1
            else:
                empates += 1

        partidas_reais = vitorias + derrotas + empates
        taxa_vitoria = (vitorias / partidas_reais) if partidas_reais else 0.0

        link.vitorias = vitorias
        link.derrotas = derrotas
        link.empates = empates
        link.byes = byes
        session.add(link)

        por_link[link.id] = {"taxa_vitoria": taxa_vitoria, "oponentes_ids": oponentes_ids}

    for link in links:
        oponentes_ids = por_link[link.id]["oponentes_ids"]
        taxas_oponentes = [por_link[oid]["taxa_vitoria"] for oid in oponentes_ids if oid in por_link]
        por_link[link.id]["omw"] = (sum(taxas_oponentes) / len(taxas_oponentes)) if taxas_oponentes else 0.0

    for link in links:
        oponentes_ids = por_link[link.id]["oponentes_ids"]
        omws_oponentes = [por_link[oid]["omw"] for oid in oponentes_ids if oid in por_link]
        oomw = (sum(omws_oponentes) / len(omws_oponentes)) if omws_oponentes else 0.0

        link.porcentagem_vitorias_oponentes = round(por_link[link.id]["omw"] * 100, 2)
        link.porcentagem_vitorias_oponentes_oponentes = round(oomw * 100, 2)
        session.add(link)


def calcular_pontuacao_rodada(session: SessionDep, rodada: Rodada, regra_basica: TipoJogador):
    """pontuacao (bruta): sempre só a regra básica do torneio, igual pra todo
    mundo, nunca afetada por regra extra — é o valor "de referência" que
    ignora qualquer ajuste por jogador.

    pontuacao_com_regras (oficial): regra básica + regra extra própria
    (opcional) + regra extra do OPONENTE (opcional), pros três resultados
    possíveis (vitória/derrota/empate):

        vitoria  = basica.pt_vitoria + (própria.pt_vitoria se tiver)
                                      + (oponente.pt_oponente_ganha se tiver)
        derrota  = basica.pt_derrota + (própria.pt_derrota se tiver)
                                      + (oponente.pt_oponente_perde se tiver)
        empate   = basica.pt_empate  + (própria.pt_empate se tiver)
                                      + (oponente.pt_oponente_empate se tiver)

    Regra extra é um AJUSTE, nunca substitui a básica — um jogador sem regra
    extra (o caso normal) pontua só pela básica. Os campos
    pt_oponente_ganha/pt_oponente_perde/pt_oponente_empate da regra BÁSICA do
    torneio não entram nessa conta — só fazem sentido numa regra extra (ver
    docs/REGRA_EXTRA.md)."""
    jogador1_id = rodada.jogador1_id
    jogador2_id = rodada.jogador2_id
    jogador1_link = rodada.jogador1
    jogador2_link = rodada.jogador2
    jogador1_extra = jogador1_link.regra_extra
    # Rodada "bye" (número ímpar de jogadores, sem oponente pareado): não gera
    # bônus de oponente pra ninguém — só a pontuação normal do resultado.
    jogador2_extra = jogador2_link.regra_extra if jogador2_link else None

    if rodada.vencedor_id == jogador1_id:
        jogador1_link.pontuacao_com_regras += (
            regra_basica.pt_vitoria
            + (jogador1_extra.pt_vitoria if jogador1_extra else 0)
            + (jogador2_extra.pt_oponente_ganha if jogador2_extra else 0)
        )
        if jogador2_link:
            jogador2_link.pontuacao_com_regras += (
                regra_basica.pt_derrota
                + (jogador2_extra.pt_derrota if jogador2_extra else 0)
                + (jogador1_extra.pt_oponente_perde if jogador1_extra else 0)
            )

        jogador1_link.pontuacao += (
            regra_basica.pt_vitoria
            + (regra_basica.pt_oponente_ganha if jogador2_link else 0)
        )

        if jogador2_link:
            jogador2_link.pontuacao += (regra_basica.pt_derrota
                                            + regra_basica.pt_oponente_perde)

    elif jogador2_link and rodada.vencedor_id == jogador2_id:
        jogador2_link.pontuacao_com_regras += (
            regra_basica.pt_vitoria
            + (jogador2_extra.pt_vitoria if jogador2_extra else 0)
            + (jogador1_extra.pt_oponente_ganha if jogador1_extra else 0)
        )
        jogador1_link.pontuacao_com_regras += (
            regra_basica.pt_derrota
            + (jogador1_extra.pt_derrota if jogador1_extra else 0)
            + (jogador2_extra.pt_oponente_perde if jogador2_extra else 0)
        )
        jogador2_link.pontuacao += (regra_basica.pt_vitoria
                                            + regra_basica.pt_oponente_ganha)

        jogador1_link.pontuacao += (regra_basica.pt_derrota
                                    + regra_basica.pt_oponente_perde)
    else:
        # Empate (ou bye sem vencedor definido).
        jogador1_link.pontuacao_com_regras += (
            regra_basica.pt_empate
            + (jogador1_extra.pt_empate if jogador1_extra else 0)
            + (jogador2_extra.pt_oponente_empate if jogador2_extra else 0)
        )
        if jogador2_link:
            jogador2_link.pontuacao_com_regras += (
                regra_basica.pt_empate
                + (jogador2_extra.pt_empate if jogador2_extra else 0)
                + (jogador1_extra.pt_oponente_empate if jogador1_extra else 0)
            )

        jogador1_link.pontuacao += (
            regra_basica.pt_empate
            + (regra_basica.pt_oponente_empate if jogador2_link else 0)
        )
        if jogador2_link:
            jogador2_link.pontuacao += (regra_basica.pt_empate
                                    + regra_basica.pt_oponente_empate)

    session.add(jogador1_link)
    if jogador2_link:
        session.add(jogador2_link)

def get_torneio_top(session: SessionDep, torneio_id: str):
    # Quem é só Juiz não entra no ranking/pódio deste torneio específico (só
    # no ranking geral entre torneios — ver docs/PONTUACAO_EXTRA.md); quem é
    # JOGADOR_E_JUIZ entra normalmente, é jogador de verdade também.
    jogadores = session.exec(
        select(JogadorTorneioLink)
        .where(
            (JogadorTorneioLink.torneio_id == torneio_id) &
            (JogadorTorneioLink.tipo.in_([
                TipoParticipanteTorneio.JOGADOR,
                TipoParticipanteTorneio.JOGADOR_E_JUIZ,
            ]))
        )
        .order_by(col(JogadorTorneioLink.pontuacao).desc())
    ).all()

    ranking = []
    for posicao, jt in enumerate(jogadores, start=1):
        jogador = jt.jogador_criado.jogador if jt.jogador_criado else None
        nome = jogador.nome if jogador else (jt.jogador_criado.apelido if jt.jogador_criado else jt.apelido)
        ranking.append({
            "posicao": posicao,
            "jogador_nome": nome,
            "pontuacao": jt.pontuacao,
            "pontuacao_com_regras": jt.pontuacao_com_regras
        })

    return ranking