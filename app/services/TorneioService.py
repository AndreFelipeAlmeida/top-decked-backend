from sqlmodel import col, select
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.models import Rodada, Torneio, Jogador, JogadorTorneioLink, TipoJogador, LojaJogadorLink, LojaJogadorOrganizadorTCG
from app.utils.Enums import TCG

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
        "tipo_jogador_id": link.tipo_jogador_id,
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
    }


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


def editar_torneio_regras(session: SessionDep, torneio: Torneio, regra_basica: int, regras_adicionais: dict):
    if regra_basica:
        torneio.regra_basica_id = regra_basica
    
    for jogador in torneio.jogadores:
        jogador.pontuacao = 0
        jogador.pontuacao_com_regras = torneio.pontuacao_de_participacao
        jogador_id = jogador.id
        
        if regras_adicionais and str(jogador_id) in regras_adicionais.keys():
            jogador.tipo_jogador_id = regras_adicionais[str(jogador_id)]
        else:
            # Usa torneio.regra_basica_id (já resolvido acima), não o parâmetro
            # `regra_basica` cru — quando o chamador não passa uma regra nova
            # (ex.: `iniciar_torneio` sem regra_basica_id, reaproveitando a que
            # o torneio já tinha), `regra_basica` aqui é None, e usá-lo direto
            # apagava o tipo_jogador_id de todo mundo (ver docs/DIVIDA_TECNICA.md).
            jogador.tipo_jogador_id = torneio.regra_basica_id
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
    jogador1_id = rodada.jogador1_id
    jogador2_id = rodada.jogador2_id
    jogador1_link = rodada.jogador1
    jogador2_link = rodada.jogador2
    jogador1_tipo = jogador1_link.tipo_jogador
    # Rodada "bye" (número ímpar de jogadores, sem oponente pareado): não gera
    # bônus de oponente para ninguém — só a pontuação normal de vitória.
    jogador2_tipo = jogador2_link.tipo_jogador if jogador2_link else None

    if rodada.vencedor_id == jogador1_id:
        # Jogador 1 ganha os pontos por vitória
        # e os pontos da regra de derrota do oponente (0 se for bye)
        jogador1_link.pontuacao_com_regras += (
            jogador1_tipo.pt_vitoria
            + (jogador2_tipo.pt_oponente_ganha if jogador2_tipo else 0)
        )
        # Jogador 2 ganha os pontos por derrota
        # e os pontos da regra de vitória do oponente (possivelmente negativos)
        if jogador2_link:
            jogador2_link.pontuacao_com_regras += (jogador2_tipo.pt_derrota
                                                    + jogador1_tipo.pt_oponente_perde)

        jogador1_link.pontuacao += (
            regra_basica.pt_vitoria
            + (regra_basica.pt_oponente_ganha if jogador2_link else 0)
        )

        if jogador2_link:
            jogador2_link.pontuacao += (regra_basica.pt_derrota
                                            + regra_basica.pt_oponente_perde)

    elif jogador2_link and rodada.vencedor_id == jogador2_id:
        # Jogador 2 ganha os pontos por vitória
        # e os pontos da regra de derrota do oponente
        jogador2_link.pontuacao_com_regras += (jogador2_tipo.pt_vitoria
                                        + jogador1_tipo.pt_oponente_ganha)
        # Jogador 1 ganha os pontos por derrota
        # e os pontos da regra de vitória do oponente (possivelmente negativos)
        jogador1_link.pontuacao_com_regras += (jogador1_tipo.pt_derrota
                                            + jogador2_tipo.pt_oponente_perde)
        jogador2_link.pontuacao += (regra_basica.pt_vitoria
                                            + regra_basica.pt_oponente_ganha)

        jogador1_link.pontuacao += (regra_basica.pt_derrota
                                    + regra_basica.pt_oponente_perde)
    else:
        # Empate (ou bye sem vencedor definido).
        # Jogador 1 ganha os pontos por empate
        # e os pontos da regra de empate do oponente (0 se for bye)
        jogador1_link.pontuacao_com_regras += (
            jogador1_tipo.pt_empate
            + (jogador2_tipo.pt_oponente_empate if jogador2_tipo else 0)
        )
        # Jogador 2 ganha os pontos por empate
        # e os pontos da regra de empate do oponente
        if jogador2_link:
            jogador2_link.pontuacao_com_regras += (jogador2_tipo.pt_empate
                                            + jogador1_tipo.pt_oponente_empate)

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
    jogadores = session.exec(
        select(JogadorTorneioLink)
        .where(JogadorTorneioLink.torneio_id == torneio_id)
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