from fastapi import APIRouter, UploadFile, Depends, Body
from sqlmodel import text
from typing import Annotated
from app.services.TorneioService import retornar_torneio_completo, retornar_link_completo, editar_torneio_regras, regras_extras_atuais, calcular_pontuacao, calcular_pontuacao_rodada, get_torneio_top, verificar_permissao_gerenciar_torneio, adicionar_juiz, remover_juiz, salvar_link_ou_conflito
from app.services.ImportacaoService import importar_torneio
from app.services.RodadaService import nova_rodada
from app.services.ConquistaService import recalcular_conquistas_jogador
from app.services.ComposicaoService import (
    JOGOS_COM_REPRESENTACAO_DECK,
    JOGOS_COM_COMPOSICAO_POR_PARTIDA,
    retornar_composicao_partida_completa,
)
from app.services.PontuacaoExtraService import (
    criar_pontuacao_extra,
    retornar_pontuacao_extra_completa,
    listar_jogadores_disponiveis,
    listar_organizadores_disponiveis_para_juiz,
)
from app.schemas.Torneio import TorneioPublico, TorneioAtualizar, CriarTorneioOrganizadorDTO
from app.schemas.JogadorTorneioLink import JogadorTorneioLinkPublico, PontuacaoManualDTO, RegraJogadorDTO, AdicionarJuizDTO
from app.schemas.Composicao import JogadorComposicaoDTO, ComposicaoPartidaPublico, ComposicaoPartidaAtualizarDTO
from app.schemas.Rodada import RodadaResultadoDTO, RodadaEditarDTO
from app.schemas.PontuacaoExtra import PontuacaoExtraCriarDTO, PontuacaoExtraPublico
from app.schemas.JogadorCriado import JogadorCriadoPublico
from app.models import TipoJogador, Loja, LojaJogadorLink, LojaJogadorOrganizadorTCG, Torneio, TorneioBase, JogadorTorneioLink, Jogador, StatusTorneio, Rodada, JogadorCriado, PontuacaoExtra, RepresentacaoComposicao, UnidadeCatalogo, JogadorComposicaoUnidade, RodadaComposicao, ComposicaoPartidaUnidade
from app.utils.Enums import TCG, MotivoPontuacaoExtra, TipoParticipanteTorneio
from app.utils.datetimeUtil import agora_brasil
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual, retornar_jogador_atual, retornar_usuario_atual, contexto_dominio
from sqlmodel import select
from sqlalchemy import func
from typing import Dict


router = APIRouter(
    prefix="/lojas/torneios",
    tags=["Torneios"])


@router.post("/criar", response_model=TorneioPublico)
def criar_torneio(session: SessionDep, torneio: TorneioBase, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    novo_torneio = Torneio(
        **torneio.model_dump(),
        loja_id=loja.id,
    )
    session.add(novo_torneio)
    session.commit()
    session.refresh(novo_torneio)
    return retornar_torneio_completo(session, novo_torneio)


@router.post(
    "/criar-organizador",
    response_model=TorneioPublico
)
def criar_torneio_organizador(
    session: SessionDep,
    torneio: CriarTorneioOrganizadorDTO,

    jogador: Annotated[
        TokenData,
        Depends(retornar_jogador_atual)
    ]
):

    loja = session.get(Loja, torneio.loja_id)

    if not loja:
        raise TopDeckedException.not_found(
            "Loja não encontrada"
        )

    link = session.exec(
        select(LojaJogadorLink)
        .where(
            (LojaJogadorLink.loja_id == torneio.loja_id) &
            (LojaJogadorLink.jogador_id == jogador.id)
        )
    ).first()

    if not link:
        raise TopDeckedException.forbidden(
            "Jogador não pertence a esta loja"
        )

    organizacoes = session.exec(
        select(LojaJogadorOrganizadorTCG)
        .where(
            LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id
        )
    ).all()

    if not organizacoes:
        raise TopDeckedException.forbidden(
            "Jogador não é organizador desta loja"
        )

    tcgs_organizados = [
        organizacao.tcg
        for organizacao in organizacoes
    ]

    if torneio.jogo not in tcgs_organizados:
        raise TopDeckedException.forbidden(
            "Jogador não possui permissão para criar torneios deste TCG"
        )

    regra = session.get(TipoJogador, torneio.regra_basica_id)

    if not regra:
        raise TopDeckedException.not_found(
            "Regra de pontuação não encontrada"
        )

    if regra.loja_id != torneio.loja_id:
        raise TopDeckedException.forbidden(
            "A regra selecionada não pertence à loja"
        )

    novo_torneio = Torneio(
        **torneio.model_dump(exclude={"loja_id"}),
        loja_id=torneio.loja_id,
    )

    session.add(novo_torneio)
    session.commit()
    session.refresh(novo_torneio)

    return retornar_torneio_completo(
        session,
        novo_torneio
    )


@router.post(
    "/importar-organizador",
    response_model=TorneioPublico
)
def importar_torneio_organizador(
    session: SessionDep,
    arquivo: UploadFile,
    loja_id: int,

    jogador: Annotated[
        TokenData,
        Depends(retornar_jogador_atual)
    ]
):

    loja = session.get(Loja, loja_id)

    if not loja:
        raise TopDeckedException.not_found(
            "Loja não encontrada"
        )

    link = session.exec(
        select(LojaJogadorLink)
        .where(
            (LojaJogadorLink.loja_id == loja_id) &
            (LojaJogadorLink.jogador_id == jogador.id)
        )
    ).first()

    if not link:
        raise TopDeckedException.forbidden(
            "Jogador não pertence a esta loja"
        )

    organizacoes = session.exec(
        select(LojaJogadorOrganizadorTCG)
        .where(
            LojaJogadorOrganizadorTCG.loja_jogador_link_id == link.id
        )
    ).all()

    if not organizacoes:
        raise TopDeckedException.forbidden(
            "Jogador não é organizador desta loja"
        )

    tcgs_organizados = [
        organizacao.tcg
        for organizacao in organizacoes
    ]

    # O formato .tdf importado é sempre do Pokémon TCG (ver ImportacaoService),
    # então só quem organiza POKEMON nesta loja pode importar por aqui.
    if TCG.POKEMON not in tcgs_organizados:
        raise TopDeckedException.forbidden(
            "Jogador não possui permissão para importar torneios deste TCG"
        )

    torneio = importar_torneio(session, arquivo, loja_id)
    session.refresh(torneio)

    return retornar_torneio_completo(
        session,
        torneio
    )


@router.put("/rodadas/finalizar")
def finalizar_varias_rodadas(
    resultados: list[RodadaResultadoDTO],
    session: SessionDep
):
    for item in resultados:
        rodada_id = item.id_rodada
        vencedor_id = item.id_vencedor

        rodada = session.get(Rodada, rodada_id)
        if not rodada:
            raise TopDeckedException.not_found(
                f"Rodada {rodada_id} não encontrada")

        if rodada.finalizada:
            raise TopDeckedException.bad_request(
                f"Rodada {rodada_id} já finalizada")

        torneio = session.get(Torneio, rodada.torneio_id)
        if not torneio:
            raise TopDeckedException.not_found("Torneio não encontrado")

        if vencedor_id is not None and vencedor_id not in [rodada.jogador1_id, rodada.jogador2_id]:
            raise TopDeckedException.bad_request(
                f"Jogador {vencedor_id} não pertence à rodada {rodada_id}"
            )

        rodada.vencedor_id = vencedor_id
        rodada.finalizada = True
        calcular_pontuacao_rodada(session, rodada, torneio.regra_basica)
        session.add(rodada)

    session.commit()
    top_ranking = get_torneio_top(session, torneio.id)

    return {"ranking": top_ranking}


@router.post("/importar", response_model=TorneioPublico)
def importar_torneios(session: SessionDep, arquivo: UploadFile, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneio = importar_torneio(session, arquivo, loja.id)
    session.refresh(torneio)

    torneio_completo = retornar_torneio_completo(session, torneio)
    return torneio_completo


@router.get("/loja", response_model=list[TorneioPublico])
def get_loja_torneios(session: SessionDep, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneios = session.exec(select(Torneio).where(
        Torneio.loja_id == loja.id
    )).all()

    if not torneios:
        raise TopDeckedException.not_found("Nenhum torneio encontrado.")
    return [retornar_torneio_completo(session, torneio) for torneio in torneios]


@router.post("/{torneio_id}/importar", response_model=TorneioPublico)
def reimportar_torneio(session: SessionDep, arquivo: UploadFile, torneio_id: str, usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    loja_id = torneio.loja_id

    session.delete(torneio)
    torneio = importar_torneio(session, arquivo, loja_id)
    session.refresh(torneio)

    torneio_completo = retornar_torneio_completo(session, torneio)
    return torneio_completo


@router.put("/{torneio_id}/iniciar", response_model=TorneioPublico)
def iniciar_torneio(session: SessionDep, torneio_id: str,
                    loja: Annotated[TokenData, Depends(retornar_loja_atual)],
                    regra_basica_id: int | None = None,
                    regras_adicionais: Dict[str, int] | None = None,
                    pontuacao_de_participacao: int | None = None
                    ):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if not torneio.loja_id == loja.id:
        raise TopDeckedException.forbidden()
    if not torneio.status == StatusTorneio.ABERTO:
        raise TopDeckedException.bad_request("Torneio não pode ser iniciado")
    if not torneio.regra_basica_id and not regra_basica_id:
        raise TopDeckedException.bad_request("Torneio está sem regra básica")

    if pontuacao_de_participacao:
        torneio.pontuacao_de_participacao = pontuacao_de_participacao

    # Preserva as regras extras já atribuídas quando quem chama (ex.: o botão
    # "Iniciar Torneio", que normalmente não reenvia isso) não está de fato
    # mexendo nelas — sem isso, iniciar o torneio apagaria a regra extra de
    # todo mundo (mesma classe de bug do item 53 de docs/DIVIDA_TECNICA.md).
    torneio = editar_torneio_regras(
        session, torneio,
        regra_basica_id,
        regras_adicionais if regras_adicionais is not None else regras_extras_atuais(torneio),
    )

    torneio.status = StatusTorneio.EM_ANDAMENTO
    session.add(torneio)
    session.commit()
    session.refresh(torneio)

    torneio_completo = retornar_torneio_completo(session, torneio)
    return torneio_completo


@router.put("/{torneio_id}/finalizar", response_model=TorneioPublico)
def finalizar_torneio(session: SessionDep, torneio_id: str, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if not torneio.loja_id == loja.id:
        raise TopDeckedException.forbidden()

    torneio.status = StatusTorneio.FINALIZADO
    # A partir daqui, toda regra de negócio (temporada, período de evento,
    # ranking mensal) passa a usar a data/hora real, nunca mais a planejada
    # — então um torneio finalizado nunca pode ficar sem elas (ver
    # TorneioDataUtil.momento_efetivo_torneio). Import (.tdf) e edição
    # manual já podem tê-las preenchido antes; se não, usa agora.
    if not torneio.inicio_real:
        torneio.inicio_real = agora_brasil()
    if not torneio.fim_real:
        torneio.fim_real = agora_brasil()
    session.add(torneio)
    session.commit()
    session.refresh(torneio)

    # Um torneio finalizado é o gatilho principal de recálculo de conquistas
    # (horas jogadas, torneios jogados, vitórias) — ver docs/CONQUISTAS.md.
    jogadores_ids = {
        link.jogador_criado.jogador_id
        for link in torneio.jogadores
        if link.jogador_criado and link.jogador_criado.jogador_id
    }
    for jogador_id in jogadores_ids:
        recalcular_conquistas_jogador(session, jogador_id)

    # recalcular_conquistas_jogador faz seus próprios commits — com
    # expire_on_commit (padrão da Session, ver app/core/db.py), isso expira
    # os atributos escalares já carregados de `torneio` (id, status, etc.).
    # `torneio.model_dump()` (dentro de retornar_torneio_completo) lê esses
    # atributos sem passar pelo mecanismo de lazy-reload do SQLAlchemy, então
    # sem este refresh a resposta saía sem `id`/`status`/etc. — um
    # ResponseValidationError sempre que este endpoint fosse chamado com
    # pelo menos um jogador com conta vinculada (nenhum teste cobria esse
    # caminho até agora).
    session.refresh(torneio)
    torneio_completo = retornar_torneio_completo(session, torneio)
    return torneio_completo


@router.post("/{torneio_id}/rodada")
def proxima_rodada(session: SessionDep, torneio_id: str, loja: Annotated[TokenData, Depends(retornar_loja_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if not torneio.loja_id == loja.id:
        raise TopDeckedException.forbidden()
    if not torneio.status == StatusTorneio.EM_ANDAMENTO:
        raise TopDeckedException.bad_request("Torneio Não foi iniciado")

    rodada = nova_rodada(session, torneio)

    session.commit()
    return rodada


@router.patch("/{torneio_id}/rodadas/{rodada_id}", response_model=TorneioPublico)
def editar_rodada(session: SessionDep,
                  torneio_id: str,
                  rodada_id: int,
                  dados: RodadaEditarDTO,
                  usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    """Edição livre de uma mesa/rodada pela aba "Rodadas" (Jogador 1/Jogador
    2, vencedor da mesa) — diferente de PUT rodadas/finalizar (uma ação em
    lote que trava a rodada depois de finalizada), esta rota pode ser chamada
    quantas vezes o organizador quiser enquanto ele ajusta os resultados."""
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    rodada = session.get(Rodada, rodada_id)
    if not rodada or rodada.torneio_id != torneio_id:
        raise TopDeckedException.not_found("Rodada não encontrada neste torneio")

    dados_informados = dados.model_dump(exclude_unset=True)

    def _validar_link_do_torneio(link_id: int | None) -> None:
        if link_id is None:
            return
        link = session.get(JogadorTorneioLink, link_id)
        if not link or link.torneio_id != torneio_id:
            raise TopDeckedException.bad_request(
                f"Jogador {link_id} não pertence a este torneio")

    novo_jogador1_id = dados_informados.get("jogador1_id", rodada.jogador1_id)
    novo_jogador2_id = dados_informados.get("jogador2_id", rodada.jogador2_id)
    _validar_link_do_torneio(novo_jogador1_id)
    _validar_link_do_torneio(novo_jogador2_id)

    if novo_jogador1_id is None and novo_jogador2_id is not None:
        raise TopDeckedException.bad_request(
            "Jogador 1 é obrigatório quando há Jogador 2")
    if novo_jogador1_id is not None and novo_jogador1_id == novo_jogador2_id:
        raise TopDeckedException.bad_request(
            "Jogador 1 e Jogador 2 não podem ser o mesmo jogador")

    pareamento_mudou = (
        novo_jogador1_id != rodada.jogador1_id or novo_jogador2_id != rodada.jogador2_id
    )

    if "jogador1_id" in dados_informados:
        rodada.jogador1_id = dados_informados["jogador1_id"]
    if "jogador2_id" in dados_informados:
        rodada.jogador2_id = dados_informados["jogador2_id"]

    # Trocar quem joga na mesa invalida qualquer resultado já declarado pra
    # essa mesa — um vencedor apontando pra um jogador que não está mais nela
    # seria um dado incoerente. O organizador precisa redeclarar o resultado
    # depois de corrigir o pareamento.
    if pareamento_mudou:
        rodada.vencedor_id = None
        rodada.finalizada = False

    if "vencedor_id" in dados_informados:
        vencedor_id = dados_informados["vencedor_id"]
        if vencedor_id is not None and vencedor_id not in (rodada.jogador1_id, rodada.jogador2_id):
            raise TopDeckedException.bad_request(
                "O vencedor da mesa precisa ser um dos jogadores desta mesa")
        rodada.vencedor_id = vencedor_id
        # Enviar vencedor_id é a declaração explícita do organizador sobre o
        # resultado da mesa — None aqui significa empate, não "ainda não
        # jogou" (BRK-302). Por isso finaliza sempre que o campo é
        # informado, mesmo quando o valor é None.
        rodada.finalizada = True

    session.add(rodada)
    session.flush()

    # calcular_pontuacao_rodada soma pontuação incrementalmente — chamar de
    # novo sem resetar dobraria os pontos. Recalcula tudo do zero (mesmo
    # mecanismo de recalcular_pontuacao_torneio), preservando regras extras
    # já atribuídas por jogador.
    if torneio.regra_basica_id:
        torneio = editar_torneio_regras(
            session, torneio, torneio.regra_basica_id, regras_extras_atuais(torneio))
        session.add(torneio)
        calcular_pontuacao(session, torneio)

    session.commit()
    session.refresh(torneio)
    return retornar_torneio_completo(session, torneio)


@router.delete("/{torneio_id}/rodadas/{num_rodada}", response_model=TorneioPublico)
def deletar_rodada(session: SessionDep,
                   torneio_id: str,
                   num_rodada: int,
                   usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    """Exclusão de uma rodada inteira (todas as mesas daquele num_rodada) —
    estritamente LIFO (BRK-302): só a última rodada gerada pode ser apagada.
    Rodadas intermediárias já foram usadas como histórico de pareamento por
    rodadas seguintes (RodadaService.nova_rodada evita reencontros olhando
    esse histórico), então apagar uma do meio deixaria pareamentos futuros
    inconsistentes com o que realmente aconteceu. O front nunca deve confiar
    cegamente: a validação real é sempre feita aqui contra o banco."""
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    maior_rodada = session.exec(
        select(func.max(Rodada.num_rodada)).where(Rodada.torneio_id == torneio_id)
    ).first()

    if maior_rodada is None:
        raise TopDeckedException.not_found("Nenhuma rodada gerada para este torneio")

    if num_rodada != maior_rodada:
        raise TopDeckedException.bad_request(
            f"Só é possível excluir a última rodada gerada (rodada {maior_rodada}); "
            "a exclusão de rodadas é sempre da mais recente para a mais antiga"
        )

    mesas = session.exec(
        select(Rodada).where(
            (Rodada.torneio_id == torneio_id) & (Rodada.num_rodada == num_rodada)
        )
    ).all()

    for mesa in mesas:
        rodada_composicoes = session.exec(
            select(RodadaComposicao).where(RodadaComposicao.rodada_id == mesa.id)
        ).all()
        for rodada_composicao in rodada_composicoes:
            composicao_partida = rodada_composicao.composicao_partida
            session.delete(rodada_composicao)
            # Pokémon GO clona uma ComposicaoPartida nova a cada rodada (ver
            # ComposicaoService.garantir_composicao_partida) — TCG/VGC
            # reaproveitam a mesma entre rodadas, então só apagamos aqui
            # quando ela é exclusiva desta rodada (GO); senão destruiríamos a
            # composição de rodadas anteriores que ainda a referenciam.
            if torneio.jogo in JOGOS_COM_COMPOSICAO_POR_PARTIDA:
                session.delete(composicao_partida)
        session.delete(mesa)

    torneio.rodada_atual = max(torneio.rodada_atual - 1, 0)
    session.add(torneio)
    session.flush()

    # Mesma lógica de recomputo do zero usada em editar_rodada — sem ela, os
    # pontos que a rodada apagada já tivesse distribuído ficariam presos em
    # pontuacao/pontuacao_com_regras mesmo sem a Rodada existir mais.
    if torneio.regra_basica_id:
        torneio = editar_torneio_regras(
            session, torneio, torneio.regra_basica_id, regras_extras_atuais(torneio))
        session.add(torneio)
        calcular_pontuacao(session, torneio)

    session.commit()
    session.refresh(torneio)
    return retornar_torneio_completo(session, torneio)


@router.put("/{torneio_id}", response_model=TorneioPublico)
def editar_torneio(session: SessionDep,
                   torneio_id: str,
                   torneio_atualizar: TorneioAtualizar,
                   usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    dados_para_atualizar = torneio_atualizar.model_dump(
        exclude={"regras_adicionais"}, exclude_unset=True)

    torneio = torneio.sqlmodel_update(dados_para_atualizar)
    session.add(torneio)

    if torneio_atualizar.regra_basica_id or torneio_atualizar.regras_adicionais:
        # Idem iniciar_torneio: "Salvar Alterações" na tela de edição envia
        # regra_basica_id sempre que o torneio já tem uma, mas não reenvia
        # regras_adicionais (a tela edita isso por jogador, num select à
        # parte) — sem preservar o que já existe, salvar qualquer campo do
        # torneio apagaria a regra extra de todo mundo.
        torneio = editar_torneio_regras(
            session, torneio,
            torneio_atualizar.regra_basica_id,
            torneio_atualizar.regras_adicionais
            if torneio_atualizar.regras_adicionais is not None
            else regras_extras_atuais(torneio),
        )

        session.add(torneio)
        calcular_pontuacao(session, torneio)

    session.commit()
    session.refresh(torneio)
    return retornar_torneio_completo(session, torneio)


@router.patch("/{torneio_id}/jogadores/{link_id}/pontuacao", response_model=JogadorTorneioLinkPublico)
def atualizar_pontuacao_manual(session: SessionDep,
                               torneio_id: str,
                               link_id: int,
                               dados: PontuacaoManualDTO,
                               usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    link = session.get(JogadorTorneioLink, link_id)
    if not link or link.torneio_id != torneio_id:
        raise TopDeckedException.not_found(
            "Inscrição não encontrada neste torneio")

    link.pontuacao = dados.pontuacao
    link.pontuacao_com_regras = dados.pontuacao_com_regras
    session.add(link)
    session.commit()
    session.refresh(link)

    return retornar_link_completo(session, torneio, link)


@router.patch("/{torneio_id}/jogadores/{link_id}/regra", response_model=TorneioPublico)
def atualizar_regra_jogador(session: SessionDep,
                            torneio_id: str,
                            link_id: int,
                            dados: RegraJogadorDTO,
                            usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    if not torneio.regra_basica_id:
        raise TopDeckedException.bad_request(
            "Defina a regra básica do torneio antes de atribuir uma regra extra a um jogador")

    link = session.get(JogadorTorneioLink, link_id)
    if not link or link.torneio_id != torneio_id:
        raise TopDeckedException.not_found(
            "Inscrição não encontrada neste torneio")

    # None = remove a regra extra deste jogador (ele passa a pontuar só pela
    # regra básica) — diferente do modelo antigo, não cai de volta pra
    # regra_basica_id: regra extra é sempre um ajuste opcional, nunca um
    # valor obrigatório (ver JogadorTorneioLinkBase.regra_extra_id).
    regra_extra_id = dados.regra_extra_id

    if regra_extra_id is not None:
        regra = session.get(TipoJogador, regra_extra_id)
        if not regra or regra.loja_id != torneio.loja_id:
            raise TopDeckedException.not_found(
                "Regra de pontuação não encontrada para esta loja")

    # Preserva a regra extra que os outros jogadores já tinham (se alguma) —
    # editar_torneio_regras zeraria a regra extra de todo mundo que não
    # estiver em regras_adicionais, e só queremos trocar a deste jogador.
    regras_adicionais = regras_extras_atuais(torneio)
    if regra_extra_id is not None:
        regras_adicionais[str(link_id)] = regra_extra_id
    else:
        regras_adicionais.pop(str(link_id), None)

    torneio = editar_torneio_regras(session, torneio, torneio.regra_basica_id, regras_adicionais)
    session.add(torneio)
    calcular_pontuacao(session, torneio)
    session.commit()
    session.refresh(torneio)

    return retornar_torneio_completo(session, torneio)


@router.get("/{torneio_id}/organizadores-disponiveis-juiz", response_model=list[JogadorCriadoPublico])
def get_organizadores_disponiveis_juiz(
    session: SessionDep,
    torneio_id: str,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    return listar_organizadores_disponiveis_para_juiz(session, torneio)


@router.post("/{torneio_id}/juizes", response_model=JogadorTorneioLinkPublico)
def adicionar_juiz_torneio(
    session: SessionDep,
    torneio_id: str,
    dados: AdicionarJuizDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    link = adicionar_juiz(session, torneio, dados.jogador_criado_id)
    return retornar_link_completo(session, torneio, link)


@router.delete("/{torneio_id}/juizes/{link_id}")
def remover_juiz_torneio(
    session: SessionDep,
    torneio_id: str,
    link_id: int,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    remover_juiz(session, torneio, link_id)
    return {"ok": True}


@router.get("/{torneio_id}/jogadores-disponiveis", response_model=list[JogadorCriadoPublico])
def get_jogadores_disponiveis_pontuacao_extra(
    session: SessionDep,
    torneio_id: str,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
    motivo: MotivoPontuacaoExtra | None = None,
):
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    return listar_jogadores_disponiveis(session, torneio, motivo)


@router.post("/{torneio_id}/pontuacao-extra", response_model=PontuacaoExtraPublico)
def criar_pontuacao_extra_torneio(
    session: SessionDep,
    torneio_id: str,
    dados: PontuacaoExtraCriarDTO,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    pontuacao_extra = criar_pontuacao_extra(session, torneio, dados)
    return retornar_pontuacao_extra_completa(pontuacao_extra)


@router.get("/{torneio_id}/pontuacao-extra", response_model=list[PontuacaoExtraPublico])
def get_pontuacao_extra_torneio(
    session: SessionDep,
    torneio_id: str,
    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
):
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    resultados = session.exec(
        select(PontuacaoExtra)
        .where(PontuacaoExtra.torneio_id == torneio_id)
        .order_by(PontuacaoExtra.criado_em.desc())
    ).all()
    return [retornar_pontuacao_extra_completa(pe) for pe in resultados]


@router.patch("/{torneio_id}/jogadores/{link_id}/composicao", response_model=JogadorTorneioLinkPublico)
def atualizar_composicao_jogador(session: SessionDep,
                                 torneio_id: str,
                                 link_id: int,
                                 dados: JogadorComposicaoDTO,
                                 usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    link = session.get(JogadorTorneioLink, link_id)
    if not link or link.torneio_id != torneio_id:
        raise TopDeckedException.not_found(
            "Inscrição não encontrada neste torneio")

    if dados.composicao_representacao_id is not None:
        if torneio.jogo not in JOGOS_COM_REPRESENTACAO_DECK:
            raise TopDeckedException.bad_request(
                f"{torneio.jogo} não tem representação de deck — só a composição completa (time) se aplica"
            )
        representacao = session.get(RepresentacaoComposicao, dados.composicao_representacao_id)
        if not representacao:
            raise TopDeckedException.not_found("Representação de composição não encontrada")
        if representacao.tcg != torneio.jogo:
            raise TopDeckedException.bad_request(
                "Essa representação não é do mesmo TCG deste torneio")

    unidades_ids = [item.unidade_catalogo_id for item in dados.composicao_unidades]
    if unidades_ids:
        unidades = session.exec(
            select(UnidadeCatalogo).where(UnidadeCatalogo.id.in_(unidades_ids))
        ).all()
        unidades_por_id = {unidade.id: unidade for unidade in unidades}

        for item in dados.composicao_unidades:
            unidade = unidades_por_id.get(item.unidade_catalogo_id)
            if not unidade:
                raise TopDeckedException.not_found("Unidade não encontrada no catálogo")
            if unidade.tcg != torneio.jogo:
                raise TopDeckedException.bad_request(
                    "Uma das unidades escolhidas não é do mesmo TCG deste torneio")

    link.composicao_representacao_id = dados.composicao_representacao_id

    # `.clear()` (não `session.delete()` item a item) é o que importa aqui —
    # cascade="all, delete-orphan" faz o flush apagar os órfãos de verdade,
    # e mantém a coleção em memória de `link.composicao_unidades` em sincronia
    # com o banco. Deletar cada item manualmente sem removê-lo da coleção do
    # relacionamento deixava o objeto excluído "preso" em `link.composicao_unidades`
    # — no `session.add(link)` logo abaixo, o cascade save-update tentava
    # processar esse objeto já apagado e estourava
    # `InvalidRequestError: Instance ... has been deleted`.
    link.composicao_unidades.clear()
    session.flush()

    for item in dados.composicao_unidades:
        link.composicao_unidades.append(JogadorComposicaoUnidade(
            unidade_catalogo_id=item.unidade_catalogo_id,
            quantidade=item.quantidade,
        ))

    session.add(link)
    session.commit()
    session.refresh(link)

    return retornar_link_completo(session, torneio, link)


@router.get(
    "/{torneio_id}/rodadas/{rodada_id}/jogadores/{link_id}/composicao-partida",
    response_model=ComposicaoPartidaPublico,
)
def get_composicao_partida(session: SessionDep,
                           torneio_id: str,
                           rodada_id: int,
                           link_id: int,
                           usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    rodada = session.get(Rodada, rodada_id)
    if not rodada or rodada.torneio_id != torneio_id:
        raise TopDeckedException.not_found("Rodada não encontrada neste torneio")

    if link_id not in (rodada.jogador1_id, rodada.jogador2_id):
        raise TopDeckedException.bad_request("Esse jogador não participa desta rodada")

    rodada_composicao = session.exec(
        select(RodadaComposicao).where(
            (RodadaComposicao.rodada_id == rodada_id) &
            (RodadaComposicao.jogador_torneio_link_id == link_id)
        )
    ).first()
    if not rodada_composicao:
        raise TopDeckedException.not_found("Composição da partida ainda não foi gerada")

    return retornar_composicao_partida_completa(rodada_composicao.composicao_partida)


@router.patch(
    "/{torneio_id}/rodadas/{rodada_id}/jogadores/{link_id}/composicao-partida",
    response_model=ComposicaoPartidaPublico,
)
def atualizar_composicao_partida(session: SessionDep,
                                 torneio_id: str,
                                 rodada_id: int,
                                 link_id: int,
                                 dados: ComposicaoPartidaAtualizarDTO,
                                 usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    if torneio.jogo not in JOGOS_COM_COMPOSICAO_POR_PARTIDA:
        raise TopDeckedException.bad_request(
            f"{torneio.jogo} usa a mesma composição em toda partida — não há o que trocar por rodada"
        )

    rodada = session.get(Rodada, rodada_id)
    if not rodada or rodada.torneio_id != torneio_id:
        raise TopDeckedException.not_found("Rodada não encontrada neste torneio")

    link = session.get(JogadorTorneioLink, link_id)
    if not link or link.torneio_id != torneio_id:
        raise TopDeckedException.not_found("Inscrição não encontrada neste torneio")

    if link_id not in (rodada.jogador1_id, rodada.jogador2_id):
        raise TopDeckedException.bad_request("Esse jogador não participa desta rodada")

    rodada_composicao = session.exec(
        select(RodadaComposicao).where(
            (RodadaComposicao.rodada_id == rodada_id) &
            (RodadaComposicao.jogador_torneio_link_id == link_id)
        )
    ).first()
    if not rodada_composicao:
        raise TopDeckedException.not_found("Composição da partida ainda não foi gerada")

    # As unidades escolhidas pra essa partida precisam ser um recorte do time
    # completo que o jogador levou pro torneio (JogadorComposicaoUnidade) —
    # nunca uma unidade nova, e essa validação/atualização nunca toca o time
    # completo em si, só a ComposicaoPartida desta rodada.
    ids_do_time = {u.unidade_catalogo_id for u in link.composicao_unidades}
    for item in dados.unidades:
        if item.unidade_catalogo_id not in ids_do_time:
            raise TopDeckedException.bad_request(
                "Uma das unidades escolhidas não faz parte do time levado para o torneio"
            )

    # `.clear()` (não `session.delete()` item a item) — ver comentário
    # equivalente em atualizar_composicao_jogador, mesmo motivo.
    composicao_partida = rodada_composicao.composicao_partida
    composicao_partida.unidades.clear()
    session.flush()

    for item in dados.unidades:
        composicao_partida.unidades.append(ComposicaoPartidaUnidade(
            unidade_catalogo_id=item.unidade_catalogo_id,
            quantidade=item.quantidade,
        ))

    session.commit()
    session.refresh(composicao_partida)

    return retornar_composicao_partida_completa(composicao_partida)


@router.post("/{torneio_id}/recalcular-pontuacao", response_model=TorneioPublico)
def recalcular_pontuacao_torneio(session: SessionDep,
                                 torneio_id: str,
                                 usuario: Annotated[TokenData, Depends(retornar_usuario_atual)],
                                 regra_basica_id: int | None = Body(default=None, embed=True),
                                 pontuacao_de_participacao: int | None = Body(default=None, embed=True)):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    # Aceita a regra e a pontuação de participação selecionadas no formulário
    # mesmo que ainda não tenham sido salvas (o organizador não deveria
    # precisar clicar em "Salvar Alterações" antes de conseguir recalcular
    # com o que acabou de escolher).
    regra_a_usar = regra_basica_id or torneio.regra_basica_id

    if not regra_a_usar:
        raise TopDeckedException.bad_request(
            "Torneio está sem regra básica definida")

    regra = session.get(TipoJogador, regra_a_usar)
    if not regra or regra.loja_id != torneio.loja_id:
        raise TopDeckedException.not_found(
            "Regra de pontuação não encontrada para esta loja")

    if pontuacao_de_participacao is not None:
        torneio.pontuacao_de_participacao = pontuacao_de_participacao

    # Reaplica a regra escolhida (zera pontuacao/pontuacao_com_regras e limpa
    # a regra extra de cada participante) e recalcula a partir das rodadas.
    # Não preserva regras extras (por-jogador) que tenham sido atribuídas
    # antes — o botão "Recalcular" é um reset explícito pra regra básica.
    torneio = editar_torneio_regras(session, torneio, regra_a_usar, None)
    torneio.regra_basica_id = regra_a_usar
    session.add(torneio)
    calcular_pontuacao(session, torneio)
    session.commit()
    session.refresh(torneio)

    return retornar_torneio_completo(session, torneio)


@router.delete("/{torneio_id}", status_code=204)
def deletar_torneio(session: SessionDep,
                    torneio_id: str,
                    usuario: Annotated[TokenData, Depends(retornar_usuario_atual)]):
    """Apaga um único torneio e tudo que depende dele. Sem migrations
    (docs/DIVIDA_TECNICA.md item 6) e sem PRAGMA foreign_keys habilitado no
    SQLite (app/core/db.py), nenhum `ondelete="CASCADE"` declarado nas
    colunas é de fato aplicado pelo banco — e várias dessas dependências
    (RodadaComposicao, ComposicaoPartida) nem têm relacionamento ORM até
    Torneio pra cascatear automaticamente. Por isso o delete é manual e
    explícito, filho antes de pai: composição por partida (Pokémon GO) →
    RodadaComposicao → composição completa do jogador → Rodada →
    JogadorTorneioLink → Torneio, mais Pontuação Extra do torneio (não
    depende de mais nada, pode sair a qualquer momento antes do Torneio).
    Não mexe em conquistas/JogadorCriado/histórico financeiro — isso
    pertence ao jogador, não ao torneio."""
    torneio = session.get(Torneio, torneio_id)
    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    composicoes_da_rodada_ou_do_jogador = """
        SELECT composicao_partida_id FROM rodadacomposicao
        WHERE rodada_id IN (SELECT id FROM rodada WHERE torneio_id = :torneio_id)
           OR jogador_torneio_link_id IN (SELECT id FROM jogadortorneiolink WHERE torneio_id = :torneio_id)
    """
    session.exec(
        text(f"DELETE FROM composicaopartidaunidade WHERE composicao_partida_id IN ({composicoes_da_rodada_ou_do_jogador})")
        .bindparams(torneio_id=torneio_id)
    )
    session.exec(
        text(f"DELETE FROM composicaopartida WHERE id IN ({composicoes_da_rodada_ou_do_jogador})")
        .bindparams(torneio_id=torneio_id)
    )
    session.exec(
        text("""
            DELETE FROM rodadacomposicao
            WHERE rodada_id IN (SELECT id FROM rodada WHERE torneio_id = :torneio_id)
               OR jogador_torneio_link_id IN (SELECT id FROM jogadortorneiolink WHERE torneio_id = :torneio_id)
        """)
        .bindparams(torneio_id=torneio_id)
    )
    session.exec(
        text("DELETE FROM jogadorcomposicaounidade WHERE jogador_torneio_link_id IN (SELECT id FROM jogadortorneiolink WHERE torneio_id = :torneio_id)")
        .bindparams(torneio_id=torneio_id)
    )
    session.exec(text("DELETE FROM rodada WHERE torneio_id = :torneio_id").bindparams(torneio_id=torneio_id))
    session.exec(text("DELETE FROM jogadortorneiolink WHERE torneio_id = :torneio_id").bindparams(torneio_id=torneio_id))
    session.exec(text("DELETE FROM pontuacaoextra WHERE torneio_id = :torneio_id").bindparams(torneio_id=torneio_id))
    session.exec(text("DELETE FROM torneio WHERE id = :torneio_id").bindparams(torneio_id=torneio_id))
    session.commit()


@router.get("/", response_model=list[TorneioPublico])
def get_torneios(
    session: SessionDep,
    loja_id: Annotated[int | None, Depends(contexto_dominio)] = None,
):
    # BRK-407: listagem global do jogador (Torneios/Rankings navegam TODAS
    # as lojas quando no domínio raiz) — mas dentro do subdomínio de uma
    # loja específica, contexto_dominio (resolvido pelo TenantHostMiddleware
    # a partir do Host, BRK-307) já trava o resultado só naquela loja. Não
    # depende do front mandar nenhum parâmetro: o Host já é a fonte da
    # verdade, então o vazamento fica barrado mesmo que o front esqueça.
    query = select(Torneio)
    if loja_id is not None:
        query = query.where(Torneio.loja_id == loja_id)

    torneios = session.exec(query)
    return [retornar_torneio_completo(session, torneio) for torneio in torneios]


@router.get("/{torneio_id}", response_model=TorneioPublico)
def get_torneio_por_loja(
    torneio_id: str,
    session: SessionDep,
    _: Annotated[TokenData, Depends(retornar_usuario_atual)]
):
    torneio = session.exec(select(Torneio).where(
        Torneio.id == torneio_id,
    )).first()

    if not torneio:
        raise TopDeckedException.not_found("Torneio não encontrado.")

    return retornar_torneio_completo(session, torneio)


@router.post("/{torneio_id}/inscricao", response_model=JogadorTorneioLinkPublico)
def inscrever_jogador(session: SessionDep, torneio_id: str, token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    torneio = session.get(Torneio, torneio_id)
    jogador = session.get(Jogador, token_data.id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    if torneio.status != StatusTorneio.ABERTO:
        raise TopDeckedException.bad_request("Torneio não está aberto para inscrições")

    jogador_criado = session.exec(select(JogadorCriado).where((JogadorCriado.jogador_id == jogador.id) &
                                                               (JogadorCriado.tcg == torneio.jogo))).first()

    if not jogador_criado:
        raise TopDeckedException.bad_request(
            f"Jogador não possui um ID para {torneio.jogo} vinculado")

    link = session.exec(select(JogadorTorneioLink)
                        .where((JogadorTorneioLink.jogador_criado_id == jogador_criado.id) &
                                (JogadorTorneioLink.torneio_id == torneio.id))).first()

    # Um jogador só tem UMA linha por torneio (fonte única de verdade). Se
    # ele já é Juiz aqui (ver TorneioService.adicionar_juiz), inscrever-se
    # é um upsert — vira JOGADOR_E_JUIZ em vez de criar uma segunda linha.
    if link:
        if link.tipo in (TipoParticipanteTorneio.JOGADOR, TipoParticipanteTorneio.JOGADOR_E_JUIZ):
            raise TopDeckedException.bad_request("Inscrição já realizada")
        link.tipo = TipoParticipanteTorneio.JOGADOR_E_JUIZ
        session.add(link)
        session.commit()
        session.refresh(link)
        return retornar_link_completo(session, torneio, link)

    # Sem regra extra na inscrição — a regra básica do torneio já se aplica
    # sozinha a todo mundo (ver JogadorTorneioLinkBase.regra_extra_id).
    inscricao = JogadorTorneioLink(
        jogador_criado_id=jogador_criado.id,
        apelido=jogador.nome,
        torneio_id=torneio.id,
        loja_id=torneio.loja_id,
        tipo=TipoParticipanteTorneio.JOGADOR,
    )

    salvar_link_ou_conflito(session, inscricao, "Inscrição já realizada")
    session.commit()
    session.refresh(inscricao)

    return retornar_link_completo(session, torneio, inscricao)


@router.delete("/{torneio_id}/inscricao", status_code=204)
def desinscrever_jogador(session: SessionDep, torneio_id: str, token_data: Annotated[TokenData, Depends(retornar_jogador_atual)]):
    torneio = session.get(Torneio, torneio_id)
    jogador = session.get(Jogador, token_data.id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")
    if torneio.status != StatusTorneio.ABERTO:
        raise TopDeckedException.bad_request("Torneio não está aberto para inscrições")

    inscricao = session.exec(
        select(JogadorTorneioLink)
        .join(JogadorCriado, JogadorCriado.id == JogadorTorneioLink.jogador_criado_id)
        .where(
            JogadorCriado.jogador_id == jogador.id,
            JogadorTorneioLink.torneio_id == torneio.id
        )
    ).first()

    if not inscricao or inscricao.tipo not in (TipoParticipanteTorneio.JOGADOR, TipoParticipanteTorneio.JOGADOR_E_JUIZ):
        raise TopDeckedException.not_found("Inscrição não encontrada")

    # Downgrade, não delete, se ele também é Juiz aqui — só sai o papel de
    # Jogador (mesma regra de TorneioService.remover_juiz, espelhada).
    if inscricao.tipo == TipoParticipanteTorneio.JOGADOR_E_JUIZ:
        inscricao.tipo = TipoParticipanteTorneio.JUIZ
        session.add(inscricao)
        session.commit()
        return

    session.delete(inscricao)
    session.commit()
