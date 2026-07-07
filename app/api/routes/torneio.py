from fastapi import APIRouter, UploadFile, Depends, Body
from sqlmodel import text
from typing import Annotated
from app.services.TorneioService import retornar_torneio_completo, retornar_link_completo, editar_torneio_regras, calcular_pontuacao, calcular_pontuacao_rodada, get_torneio_top, verificar_permissao_gerenciar_torneio
from app.services.ImportacaoService import importar_torneio
from app.services.RodadaService import nova_rodada
from app.services.ConquistaService import recalcular_conquistas_jogador
from app.services.ComposicaoService import (
    JOGOS_COM_REPRESENTACAO_DECK,
    JOGOS_COM_COMPOSICAO_POR_PARTIDA,
    retornar_composicao_partida_completa,
)
from app.schemas.Torneio import TorneioPublico, TorneioAtualizar, CriarTorneioOrganizadorDTO
from app.schemas.JogadorTorneioLink import JogadorTorneioLinkPublico, PontuacaoManualDTO, RegraJogadorDTO
from app.schemas.Composicao import JogadorComposicaoDTO, ComposicaoPartidaPublico, ComposicaoPartidaAtualizarDTO
from app.schemas.Rodada import RodadaResultadoDTO, RodadaEditarDTO
from app.models import TipoJogador, Loja, LojaJogadorLink, LojaJogadorOrganizadorTCG, Torneio, TorneioBase, JogadorTorneioLink, Jogador, StatusTorneio, Rodada, JogadorCriado, RepresentacaoComposicao, UnidadeCatalogo, JogadorComposicaoUnidade, RodadaComposicao, ComposicaoPartidaUnidade
from app.utils.Enums import TCG
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.core.security import TokenData
from app.dependencies import retornar_loja_atual, retornar_jogador_atual, retornar_usuario_atual
from sqlmodel import select
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

    torneio = editar_torneio_regras(session, torneio,
                                    regra_basica_id,
                                    regras_adicionais)

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
        rodada.finalizada = vencedor_id is not None

    session.add(rodada)
    session.flush()

    # calcular_pontuacao_rodada soma pontuação incrementalmente — chamar de
    # novo sem resetar dobraria os pontos. Recalcula tudo do zero (mesmo
    # mecanismo de recalcular_pontuacao_torneio), preservando regras
    # específicas por jogador já atribuídas.
    if torneio.regra_basica_id:
        regras_adicionais = {
            str(jt.id): jt.tipo_jogador_id
            for jt in torneio.jogadores
            if jt.tipo_jogador_id is not None
        }
        torneio = editar_torneio_regras(session, torneio, torneio.regra_basica_id, regras_adicionais)
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
        torneio = editar_torneio_regras(session, torneio,
                                        torneio_atualizar.regra_basica_id,
                                        torneio_atualizar.regras_adicionais)

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
            "Defina a regra básica do torneio antes de atribuir uma regra específica a um jogador")

    link = session.get(JogadorTorneioLink, link_id)
    if not link or link.torneio_id != torneio_id:
        raise TopDeckedException.not_found(
            "Inscrição não encontrada neste torneio")

    tipo_jogador_id = dados.tipo_jogador_id or torneio.regra_basica_id

    regra = session.get(TipoJogador, tipo_jogador_id)
    if not regra or regra.loja_id != torneio.loja_id:
        raise TopDeckedException.not_found(
            "Regra de pontuação não encontrada para esta loja")

    # Preserva a regra específica que os outros jogadores já tinham (se
    # alguma) — editar_torneio_regras reatribuiria todo mundo pra regra
    # básica se regras_adicionais não cobrisse todo mundo, e só queremos
    # trocar a regra deste jogador.
    regras_adicionais = {
        str(jt.id): jt.tipo_jogador_id
        for jt in torneio.jogadores
        if jt.tipo_jogador_id is not None
    }
    regras_adicionais[str(link_id)] = tipo_jogador_id

    torneio = editar_torneio_regras(session, torneio, torneio.regra_basica_id, regras_adicionais)
    session.add(torneio)
    calcular_pontuacao(session, torneio)
    session.commit()
    session.refresh(torneio)

    return retornar_torneio_completo(session, torneio)


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
                                 regra_basica_id: int | None = Body(default=None, embed=True)):
    torneio = session.get(Torneio, torneio_id)

    if not torneio:
        raise TopDeckedException.not_found("Torneio não existe")

    verificar_permissao_gerenciar_torneio(session, torneio, usuario)

    # Aceita a regra selecionada no formulário mesmo que ainda não tenha sido
    # salva (o organizador não deveria precisar clicar em "Salvar Alterações"
    # antes de conseguir recalcular com a regra que acabou de escolher).
    regra_a_usar = regra_basica_id or torneio.regra_basica_id

    if not regra_a_usar:
        raise TopDeckedException.bad_request(
            "Torneio está sem regra básica definida")

    regra = session.get(TipoJogador, regra_a_usar)
    if not regra or regra.loja_id != torneio.loja_id:
        raise TopDeckedException.not_found(
            "Regra de pontuação não encontrada para esta loja")

    # Reaplica a regra escolhida (zera pontuacao/pontuacao_com_regras e reatribui
    # tipo_jogador_id de cada participante) e recalcula a partir das rodadas. Não
    # preserva regras adicionais (por-jogador) que tenham sido atribuídas antes —
    # a tela de edição atual não expõe esse ajuste fino.
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
    JogadorTorneioLink → Torneio. Não mexe em conquistas/JogadorCriado/histórico
    financeiro — isso pertence ao jogador, não ao torneio."""
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
    session.exec(text("DELETE FROM torneio WHERE id = :torneio_id").bindparams(torneio_id=torneio_id))
    session.commit()


@router.get("/", response_model=list[TorneioPublico])
def get_torneios(session: SessionDep):
    torneios = session.exec(select(Torneio))
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
    if link:
        raise TopDeckedException.bad_request("Inscrição já realizada")

    inscricao = JogadorTorneioLink(
        jogador_criado_id=jogador_criado.id,
        apelido=jogador.nome,
        torneio_id=torneio.id,
        tipo_jogador_id=torneio.regra_basica_id if torneio.regra_basica_id else None,
    )

    session.add(inscricao)
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

    if not inscricao:
        raise TopDeckedException.not_found("Inscrição não encontrada")

    session.delete(inscricao)
    session.commit()
