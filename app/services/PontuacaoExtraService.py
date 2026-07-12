from sqlmodel import select
from app.core.db import SessionDep
from app.core.exception import TopDeckedException
from app.models import (
    Jogador,
    JogadorCriado,
    JogadorTorneioLink,
    LojaJogadorLink,
    LojaJogadorOrganizadorTCG,
    PontuacaoExtra,
    Torneio,
)
from app.schemas.PontuacaoExtra import PontuacaoExtraCriarDTO
from app.services.TorneioService import salvar_link_ou_conflito
from app.utils.Enums import MotivoPontuacaoExtra, TipoParticipanteTorneio


def criar_pontuacao_extra(session: SessionDep, torneio: Torneio, dados: PontuacaoExtraCriarDTO) -> PontuacaoExtra:
    """Dá pontos extras a um jogador neste torneio, sempre em cima de
    `pontuacao_com_regras` (nunca em `pontuacao`, a "crua" — ver
    docs/PONTUACAO_EXTRA.md). Um jogador só tem UMA linha de
    JogadorTorneioLink por torneio (fonte única de verdade — ver
    TipoParticipanteTorneio.JOGADOR_E_JUIZ), então basta achar essa linha.
    Se ainda não existir, cria uma na hora — exceto pro motivo Juiz, que
    exige o papel de Juiz já cadastrado (via TorneioService.adicionar_juiz):
    dar pontos não é mais o que "torna" alguém Juiz do torneio."""
    jogador_criado = session.get(JogadorCriado, dados.jogador_criado_id)
    if not jogador_criado:
        raise TopDeckedException.not_found("Jogador não encontrado")
    if jogador_criado.tcg != torneio.jogo:
        raise TopDeckedException.bad_request(
            "Esse jogador não tem cadastro para o jogo deste torneio")

    link = session.exec(
        select(JogadorTorneioLink).where(
            (JogadorTorneioLink.torneio_id == torneio.id) &
            (JogadorTorneioLink.jogador_criado_id == dados.jogador_criado_id)
        )
    ).first()

    if dados.motivo == MotivoPontuacaoExtra.JUIZ:
        eh_juiz = link and link.tipo in (
            TipoParticipanteTorneio.JUIZ, TipoParticipanteTorneio.JOGADOR_E_JUIZ)
        if not eh_juiz:
            raise TopDeckedException.bad_request(
                "Jogador não está cadastrado como Juiz neste torneio. "
                "Cadastre-o na aba principal antes de atribuir pontos extras."
            )
    elif not link:
        link = JogadorTorneioLink(
            torneio_id=torneio.id,
            jogador_criado_id=dados.jogador_criado_id,
            apelido=jogador_criado.apelido or jogador_criado.game_id,
            tipo=TipoParticipanteTorneio.JOGADOR,
        )
        salvar_link_ou_conflito(session, link, "Este jogador já participa deste torneio.")

    link.pontuacao_com_regras += dados.pontos
    session.add(link)

    pontuacao_extra = PontuacaoExtra(
        torneio_id=torneio.id,
        jogador_criado_id=dados.jogador_criado_id,
        motivo=dados.motivo,
        descricao=dados.descricao,
        pontos=dados.pontos,
    )
    session.add(pontuacao_extra)
    session.commit()
    session.refresh(pontuacao_extra)
    return pontuacao_extra


def retornar_pontuacao_extra_completa(pontuacao_extra: PontuacaoExtra) -> dict:
    jogador_criado = pontuacao_extra.jogador_criado
    return {
        "id": pontuacao_extra.id,
        "torneio_id": pontuacao_extra.torneio_id,
        "jogador_criado_id": pontuacao_extra.jogador_criado_id,
        "motivo": pontuacao_extra.motivo,
        "descricao": pontuacao_extra.descricao,
        "pontos": pontuacao_extra.pontos,
        "criado_em": pontuacao_extra.criado_em,
        "apelido": jogador_criado.apelido if jogador_criado else None,
        "game_id": jogador_criado.game_id if jogador_criado else None,
        "torneio_nome": pontuacao_extra.torneio.nome if pontuacao_extra.torneio else None,
        "jogo": pontuacao_extra.torneio.jogo if pontuacao_extra.torneio else None,
    }


def _ordenar_por_nome(jogadores) -> list[JogadorCriado]:
    return sorted(jogadores, key=lambda jc: (jc.apelido or jc.game_id or "").lower())


def listar_jogadores_do_torneio(session: SessionDep, torneio: Torneio) -> list[JogadorCriado]:
    """Quem já está participando deste torneio (mesmo sem vínculo direto com
    a loja — ex.: participante que entrou só por import de .tdf)."""
    ja_no_torneio_ids = [link.jogador_criado_id for link in torneio.jogadores]
    if not ja_no_torneio_ids:
        return []

    jogadores = session.exec(
        select(JogadorCriado).where(JogadorCriado.id.in_(ja_no_torneio_ids))
    ).all()
    return _ordenar_por_nome(jogadores)


def listar_organizadores_da_loja(session: SessionDep, torneio: Torneio) -> list[JogadorCriado]:
    """Organizadores da loja para o TCG do torneio — candidatos a serem
    cadastrados como Juiz deste torneio (ver TorneioService.adicionar_juiz)."""
    organizadores = session.exec(
        select(JogadorCriado)
        .join(Jogador, Jogador.id == JogadorCriado.jogador_id)
        .join(LojaJogadorLink, LojaJogadorLink.jogador_id == Jogador.id)
        .join(
            LojaJogadorOrganizadorTCG,
            LojaJogadorOrganizadorTCG.loja_jogador_link_id == LojaJogadorLink.id,
        )
        .where(
            (LojaJogadorLink.loja_id == torneio.loja_id) &
            (LojaJogadorOrganizadorTCG.tcg == torneio.jogo) &
            (JogadorCriado.tcg == torneio.jogo)
        )
    ).all()
    return _ordenar_por_nome(organizadores)


def listar_organizadores_disponiveis_para_juiz(session: SessionDep, torneio: Torneio) -> list[JogadorCriado]:
    """Organizadores da loja que ainda não são Juiz deste torneio — a lista
    usada pelo painel de cadastro de Juízes na aba principal do torneio."""
    ja_juizes_ids = {
        link.jogador_criado_id for link in torneio.jogadores
        if link.tipo in (TipoParticipanteTorneio.JUIZ, TipoParticipanteTorneio.JOGADOR_E_JUIZ)
    }
    return [
        jc for jc in listar_organizadores_da_loja(session, torneio)
        if jc.id not in ja_juizes_ids
    ]


def listar_juizes_do_torneio(session: SessionDep, torneio: Torneio) -> list[JogadorCriado]:
    """Juízes já cadastrados neste torneio (tipo JUIZ ou JOGADOR_E_JUIZ em
    JogadorTorneioLink) — só estes podem receber Pontuação Extra com motivo
    Juiz."""
    juiz_ids = [
        link.jogador_criado_id for link in torneio.jogadores
        if link.tipo in (TipoParticipanteTorneio.JUIZ, TipoParticipanteTorneio.JOGADOR_E_JUIZ)
    ]
    if not juiz_ids:
        return []

    jogadores = session.exec(
        select(JogadorCriado).where(JogadorCriado.id.in_(juiz_ids))
    ).all()
    return _ordenar_por_nome(jogadores)


def listar_jogadores_disponiveis(
    session: SessionDep, torneio: Torneio, motivo: MotivoPontuacaoExtra | None = None,
) -> list[JogadorCriado]:
    """Jogadores selecionáveis pra dar Pontuação Extra — a lista depende do
    motivo: Juiz mostra só quem já foi cadastrado como Juiz deste torneio;
    Trouxe um Novato mostra só quem já está no torneio; Outros (ou sem motivo
    ainda selecionado) mostra os dois grupos combinados."""
    if motivo == MotivoPontuacaoExtra.JUIZ:
        return listar_juizes_do_torneio(session, torneio)

    if motivo == MotivoPontuacaoExtra.NOVATO:
        return listar_jogadores_do_torneio(session, torneio)

    por_id = {jc.id: jc for jc in listar_jogadores_do_torneio(session, torneio)}
    for jc in listar_juizes_do_torneio(session, torneio):
        por_id[jc.id] = jc

    return _ordenar_por_nome(por_id.values())
