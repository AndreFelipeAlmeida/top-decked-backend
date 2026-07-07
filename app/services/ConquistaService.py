from datetime import datetime
from sqlmodel import select, func
from app.core.db import SessionDep
from app.models import (
    Conquista,
    ConquistaNivel,
    HistoricoConquista,
    JogadorConquista,
    JogadorCriado,
    JogadorTorneioLink,
    Rodada,
    Torneio,
)
from app.utils.Enums import CategoriaConquista, StatusTorneio
from app.utils.datetimeUtil import agora_brasil


def recalcular_conquistas_jogador(session: SessionDep, jogador_id: int) -> list[JogadorConquista]:
    """Recalcula o progresso do jogador em todas as conquistas ativas a partir
    dos dados brutos (torneios, rodadas). Não guarda contadores incrementais —
    sempre reconstrói o progresso do zero, no mesmo espírito de
    JogadorService.calcular_estatisticas. Retorna as JogadorConquista que subiram
    de nível nesta chamada (para o chamador notificar o frontend)."""
    progresso_por_categoria = {
        CategoriaConquista.HORAS_JOGADAS: _calcular_horas_jogadas(session, jogador_id),
        CategoriaConquista.TORNEIOS_JOGADOS: _calcular_torneios_jogados(session, jogador_id),
        CategoriaConquista.VITORIAS: _calcular_vitorias(session, jogador_id),
        # COMPOSICOES_JOGADAS fica de fora até existir uma função de cálculo pra ela.
    }

    conquistas = session.exec(
        select(Conquista).where(Conquista.ativa == True)
    ).all()
    subiram_de_nivel = []

    for conquista in conquistas:
        progresso = progresso_por_categoria.get(conquista.categoria)
        if progresso is None:
            continue

        niveis = sorted(conquista.niveis, key=lambda n: n.nivel)

        jc = session.exec(
            select(JogadorConquista).where(
                (JogadorConquista.jogador_id == jogador_id) &
                (JogadorConquista.conquista_id == conquista.id)
            )
        ).first() or JogadorConquista(jogador_id=jogador_id, conquista_id=conquista.id)

        jc.progresso_atual = progresso

        novo_nivel = 0
        for nivel_def in niveis:
            if progresso >= nivel_def.meta:
                novo_nivel = nivel_def.nivel
            else:
                break

        if novo_nivel > jc.nivel_atual:
            for nivel_cruzado in range(jc.nivel_atual + 1, novo_nivel + 1):
                _registrar_historico(session, jogador_id, conquista.id, nivel_cruzado, progresso)

            jc.nivel_atual = novo_nivel
            jc.nivel_atual_em = agora_brasil()
            subiram_de_nivel.append(jc)

        session.add(jc)

    session.commit()
    return subiram_de_nivel


def _registrar_historico(session: SessionDep, jogador_id: int, conquista_id: int, nivel: int, progresso: float):
    ja_existe = session.exec(
        select(HistoricoConquista).where(
            (HistoricoConquista.jogador_id == jogador_id) &
            (HistoricoConquista.conquista_id == conquista_id) &
            (HistoricoConquista.nivel == nivel)
        )
    ).first()
    if ja_existe:
        return

    session.add(HistoricoConquista(
        jogador_id=jogador_id,
        conquista_id=conquista_id,
        nivel=nivel,
        progresso_no_momento=progresso,
    ))


def _calcular_horas_jogadas(session: SessionDep, jogador_id: int) -> float:
    links = session.exec(
        select(JogadorTorneioLink)
        .join(Torneio)
        .join(JogadorCriado, JogadorCriado.id == JogadorTorneioLink.jogador_criado_id)
        .where(
            (JogadorCriado.jogador_id == jogador_id) &
            (Torneio.status == StatusTorneio.FINALIZADO)
        )
    ).all()

    segundos = 0
    for link in links:
        inicio, fim = _calcular_janela_pessoal(session, link)
        if inicio and fim and fim > inicio:
            segundos += (fim - inicio).total_seconds()

    return round(segundos / 3600, 2)


def _calcular_janela_pessoal(session: SessionDep, link: JogadorTorneioLink) -> tuple[datetime | None, datetime | None]:
    """Janela de tempo que ESTE jogador realmente jogou dentro do torneio —
    não necessariamente a janela do torneio inteiro (cobre o caso de quem
    entrou atrasado ou desistiu no meio). Ver docs/CONQUISTAS.md seção 4.1."""
    rodadas_do_jogador = session.exec(
        select(Rodada).where(
            (Rodada.torneio_id == link.torneio_id) &
            ((Rodada.jogador1_id == link.id) | (Rodada.jogador2_id == link.id))
        )
    ).all()

    if not rodadas_do_jogador:
        return None, None

    primeira_rodada_jogador = min(r.num_rodada for r in rodadas_do_jogador)
    ultima_rodada_jogador = max(r.num_rodada for r in rodadas_do_jogador)

    numeros_rodadas_torneio = session.exec(
        select(Rodada.num_rodada).where(Rodada.torneio_id == link.torneio_id)
    ).all()
    if not numeros_rodadas_torneio:
        return None, None

    primeira_rodada_torneio = min(numeros_rodadas_torneio)
    ultima_rodada_torneio = max(numeros_rodadas_torneio)

    torneio = link.torneio

    if primeira_rodada_jogador == primeira_rodada_torneio and torneio.inicio_real:
        inicio = torneio.inicio_real
    else:
        inicio = _extremo_timestamp_rodada(session, link.torneio_id, primeira_rodada_jogador, pegar_maior=False)

    if ultima_rodada_jogador == ultima_rodada_torneio and torneio.fim_real:
        fim = torneio.fim_real
    else:
        fim = _extremo_timestamp_rodada(session, link.torneio_id, ultima_rodada_jogador, pegar_maior=True)

    return inicio, fim


def _extremo_timestamp_rodada(session: SessionDep, torneio_id: str, num_rodada: int, pegar_maior: bool) -> datetime | None:
    stamps = session.exec(
        select(Rodada.data_de_inicio).where(
            (Rodada.torneio_id == torneio_id) & (Rodada.num_rodada == num_rodada)
        )
    ).all()
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        return None
    return max(stamps) if pegar_maior else min(stamps)


def _calcular_torneios_jogados(session: SessionDep, jogador_id: int) -> int:
    return session.exec(
        select(func.count(JogadorTorneioLink.id))
        .join(Torneio)
        .join(JogadorCriado, JogadorCriado.id == JogadorTorneioLink.jogador_criado_id)
        .where(
            (JogadorCriado.jogador_id == jogador_id) &
            (Torneio.status == StatusTorneio.FINALIZADO)
        )
    ).one()


def _calcular_vitorias(session: SessionDep, jogador_id: int) -> int:
    return session.exec(
        select(func.count(Rodada.id))
        .join(JogadorTorneioLink, Rodada.vencedor_id == JogadorTorneioLink.id)
        .join(JogadorCriado, JogadorCriado.id == JogadorTorneioLink.jogador_criado_id)
        .where(JogadorCriado.jogador_id == jogador_id)
    ).one()


# Catálogo semente — ver docs/CONQUISTAS.md seção 7. Ajustável sem migração:
# só editar esta lista (não afeta jogadores que já desbloquearam níveis).
_CATALOGO_SEMENTE = [
    {
        "codigo": "HORAS_JOGADAS",
        "nome": "Maratonista",
        "descricao": "Acumule horas jogando torneios do início ao fim",
        "categoria": CategoriaConquista.HORAS_JOGADAS,
        "icone": "🕐",
        "niveis": [
            (1, "Bronze", 10),
            (2, "Prata", 100),
            (3, "Ouro", 300),
            (4, "Platina", 700),
            (5, "Diamante", 1500),
        ],
    },
    {
        "codigo": "TORNEIOS_JOGADOS",
        "nome": "Frequentador",
        "descricao": "Jogue torneios finalizados",
        "categoria": CategoriaConquista.TORNEIOS_JOGADOS,
        "icone": "🏟️",
        "niveis": [
            (1, "Bronze", 5),
            (2, "Prata", 25),
            (3, "Ouro", 75),
            (4, "Platina", 150),
            (5, "Diamante", 300),
        ],
    },
    {
        "codigo": "VITORIAS",
        "nome": "Vencedor",
        "descricao": "Vença partidas em torneios",
        "categoria": CategoriaConquista.VITORIAS,
        "icone": "🏆",
        "niveis": [
            (1, "Bronze", 5),
            (2, "Prata", 25),
            (3, "Ouro", 75),
            (4, "Platina", 200),
            (5, "Diamante", 500),
        ],
    },
]


def seed_conquistas_catalogo(session: SessionDep):
    """Popula o catálogo de conquistas na primeira execução. Idempotente —
    não faz nada se já existir alguma Conquista cadastrada."""
    if session.exec(select(Conquista)).first():
        return

    for definicao in _CATALOGO_SEMENTE:
        conquista = Conquista(
            codigo=definicao["codigo"],
            nome=definicao["nome"],
            descricao=definicao["descricao"],
            categoria=definicao["categoria"],
            icone=definicao["icone"],
        )
        session.add(conquista)
        session.commit()
        session.refresh(conquista)

        for nivel, nome_nivel, meta in definicao["niveis"]:
            session.add(ConquistaNivel(
                conquista_id=conquista.id,
                nivel=nivel,
                nome_nivel=nome_nivel,
                meta=meta,
            ))

    session.commit()
