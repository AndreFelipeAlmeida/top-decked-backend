"""Suíte de isolamento de RLS (BRK-306) — roda contra um Postgres efêmero
real via testcontainers (ver conftest.py), não o SQLite da suíte principal.
PULA (skip, não falha) automaticamente se o Docker não estiver disponível
neste ambiente — rode `docker info` pra confirmar que o daemon está de pé
antes de esperar que esta suíte execute de verdade.

Também cobre o trigger de integridade loja_id (BRK-304), que pela mesma
razão (recurso Postgres-only: ALTER TYPE/PL-pgSQL) não é exercitado pela
suíte principal em SQLite."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import Engine


def test_select_torneio_so_ve_dados_da_propria_loja(pg_engine: Engine, duas_lojas_com_torneio: dict):
    loja_a = duas_lojas_com_torneio["a"]

    with pg_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.current_loja_id = :loja_id"), {"loja_id": loja_a["loja_id"]})
        torneios = conn.execute(text("SELECT id, loja_id FROM torneio")).fetchall()

    assert len(torneios) == 1
    assert torneios[0].id == loja_a["torneio_id"]
    assert torneios[0].loja_id == loja_a["loja_id"]


def test_select_sem_tenant_definido_nao_retorna_nenhuma_linha(pg_engine: Engine, duas_lojas_com_torneio: dict):
    """Fail-closed: sem `app.current_loja_id` definido, `current_setting(...,
    true)` retorna NULL, e `loja_id = NULL` nunca é verdadeiro em SQL — uma
    conexão que "esqueceu" de definir o tenant não vaza dados de ninguém,
    só não vê nada."""
    with pg_engine.begin() as conn:
        torneios = conn.execute(text("SELECT id FROM torneio")).fetchall()

    assert torneios == []


def test_insert_com_loja_id_divergente_do_tenant_e_rejeitado(pg_engine: Engine, duas_lojas_com_torneio: dict):
    loja_a = duas_lojas_com_torneio["a"]
    loja_b = duas_lojas_com_torneio["b"]

    with pytest.raises(DBAPIError):
        with pg_engine.begin() as conn:
            conn.execute(text("SET LOCAL app.current_loja_id = :loja_id"), {"loja_id": loja_a["loja_id"]})
            # WITH CHECK exige loja_id == tenant da sessão — inserir uma
            # linha apontando pra loja_b enquanto autenticado como loja_a
            # tem que ser barrado pela policy, não só pela aplicação.
            conn.execute(text(
                "INSERT INTO torneio (id, loja_id, jogo, melhor_de, tipo, data_planejada, "
                "vagas, tempo_por_rodada, n_rodadas, rodada_atual, taxa, pontuacao_de_participacao) "
                "VALUES ('torneio-insert-cruzado', :loja_id, 'POKEMON', 'MD1', 'CRIADO', "
                "'2026-08-01', 8, 30, 0, 0, 0, 0)"
            ), {"loja_id": loja_b["loja_id"]})


def test_trigger_rejeita_jogadortorneiolink_com_loja_id_divergente_do_torneio_pai(
    pg_engine: Engine, duas_lojas_com_torneio: dict
):
    """BRK-304: mesmo estando dentro do tenant certo pra passar a policy de
    RLS (loja_id da linha == tenant da sessão), o trigger de integridade
    ainda barra se esse loja_id não bater com o loja_id do torneio
    referenciado — as duas defesas são independentes."""
    loja_a = duas_lojas_com_torneio["a"]
    loja_b = duas_lojas_com_torneio["b"]

    with pytest.raises(DBAPIError):
        with pg_engine.begin() as conn:
            conn.execute(text("SET LOCAL app.current_loja_id = :loja_id"), {"loja_id": loja_a["loja_id"]})
            usuario_id = conn.execute(text(
                "INSERT INTO usuario (email, is_active, data_cadastro, tipo, senha) "
                "VALUES ('jogador.trigger.rls@gmail.com', true, now(), 'jogador', 'x') RETURNING id"
            )).scalar_one()
            jogador_id = conn.execute(text(
                "INSERT INTO jogador (nome, usuario_id) VALUES ('Jogador Trigger', :usuario_id) RETURNING id"
            ), {"usuario_id": usuario_id}).scalar_one()
            jogador_criado_id = conn.execute(text(
                "INSERT INTO jogadorcriado (game_id, tcg, jogador_id) "
                "VALUES ('gid-trigger-rls', 'POKEMON', :jogador_id) RETURNING id"
            ), {"jogador_id": jogador_id}).scalar_one()

            # loja_id aqui é o da loja_a (passa a policy de RLS), mas
            # torneio_id aponta pro torneio da loja_b — só o trigger pega isso.
            conn.execute(text(
                "INSERT INTO jogadortorneiolink (jogador_criado_id, torneio_id, loja_id, tipo, "
                "pontuacao, pontuacao_com_regras, vitorias, derrotas, empates, byes) "
                "VALUES (:jogador_criado_id, :torneio_id, :loja_id, 'JOGADOR', 0, 0, 0, 0, 0, 0)"
            ), {
                "jogador_criado_id": jogador_criado_id,
                "torneio_id": loja_b["torneio_id"],
                "loja_id": loja_a["loja_id"],
            })
