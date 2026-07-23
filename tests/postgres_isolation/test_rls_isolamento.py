import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.dependencies import definir_tenant_sessao


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


def test_leitura_publica_ve_torneios_de_todas_as_lojas(pg_engine: Engine, duas_lojas_com_torneio: dict):
    with pg_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.leitura_publica = 'on'"))
        torneios = conn.execute(text("SELECT id FROM torneio")).fetchall()

    ids = {t.id for t in torneios}
    assert duas_lojas_com_torneio["a"]["torneio_id"] in ids
    assert duas_lojas_com_torneio["b"]["torneio_id"] in ids


def test_leitura_publica_nao_afeta_pontuacaoextra(pg_engine: Engine, duas_lojas_com_torneio: dict):
    loja_a = duas_lojas_com_torneio["a"]

    with pg_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.current_loja_id = :loja_id"), {"loja_id": loja_a["loja_id"]})
        usuario_id = conn.execute(text(
            "INSERT INTO usuario (email, is_active, data_cadastro, tipo, senha) "
            "VALUES ('jogador.pontuacaoextra.rls@gmail.com', true, now(), 'jogador', 'x') RETURNING id"
        )).scalar_one()
        jogador_id = conn.execute(text(
            "INSERT INTO jogador (nome, usuario_id) VALUES ('Jogador PontuacaoExtra', :usuario_id) RETURNING id"
        ), {"usuario_id": usuario_id}).scalar_one()
        jogador_criado_id = conn.execute(text(
            "INSERT INTO jogadorcriado (game_id, tcg, jogador_id) "
            "VALUES ('gid-pontuacaoextra-rls', 'POKEMON', :jogador_id) RETURNING id"
        ), {"jogador_id": jogador_id}).scalar_one()
        conn.execute(text(
            "INSERT INTO pontuacaoextra (jogador_criado_id, motivo, pontos, torneio_id, loja_id, criado_em) "
            "VALUES (:jogador_criado_id, 'OUTROS', 5, :torneio_id, :loja_id, now())"
        ), {
            "jogador_criado_id": jogador_criado_id,
            "torneio_id": loja_a["torneio_id"],
            "loja_id": loja_a["loja_id"],
        })

    with pg_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.leitura_publica = 'on'"))
        linhas = conn.execute(text("SELECT id FROM pontuacaoextra")).fetchall()

    assert linhas == []


def test_tenant_sobrevive_a_commit_intermediario_na_mesma_session(
    pg_engine: Engine, duas_lojas_com_torneio: dict
):
    loja_a = duas_lojas_com_torneio["a"]

    with Session(pg_engine) as session:
        definir_tenant_sessao(session, loja_a["loja_id"])

        antes = session.exec(text("SELECT id FROM torneio")).fetchall()
        assert len(antes) == 1
        assert antes[0].id == loja_a["torneio_id"]

        # Commit intermediário — SET LOCAL da transação anterior é
        # descartado pelo Postgres neste ponto.
        session.commit()

        depois = session.exec(text("SELECT id FROM torneio")).fetchall()
        assert len(depois) == 1
        assert depois[0].id == loja_a["torneio_id"]


def test_trigger_rejeita_jogadortorneiolink_com_loja_id_divergente_do_torneio_pai(
    pg_engine: Engine, duas_lojas_com_torneio: dict
):
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
