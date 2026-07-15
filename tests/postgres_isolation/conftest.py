"""Fixtures da suíte de isolamento de RLS (BRK-306) — a única suíte deste
projeto que roda contra um Postgres real (efêmero, via testcontainers), não
o SQLite em memória de tests/conftest.py. RLS (Row-Level Security) é um
recurso nativo do Postgres sem equivalente em SQLite, então não dá pra
validar as policies (migrations/versions/*_rls_tabelas_escopadas_por_loja.py)
na suíte principal — só rodando contra o motor de banco de verdade.

Pula (não falha) a suíte inteira quando o Docker não está disponível/rodando
neste ambiente — ver módulo docstring de test_rls_isolamento.py."""
import uuid

import pytest
from alembic import command
from alembic.config import Config
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

# Mesma lista de migrations/versions/*_rls_tabelas_escopadas_por_loja.py —
# duplicada aqui de propósito (não importada) pra a fixture não silenciosamente
# ficar defasada se a migration for tocada sem revisar o teste também.
_TABELAS_COM_RLS = (
    "jogadortorneiolink", "rodada", "pontuacaoextra", "temporada", "evento",
    "torneio", "tipojogador",
)


@pytest.fixture(scope="session")
def pg_engine() -> Engine:
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers não instalado (pip install testcontainers)")

    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as erro:  # noqa: BLE001 — qualquer falha de Docker (daemon parado, imagem inacessível, etc.) só pula a suíte.
        pytest.skip(f"Postgres efêmero indisponível (Docker não está rodando?): {erro}")
        return  # pragma: no cover — só pra o type checker, pytest.skip já interrompe.

    try:
        from app.core.config import settings
        url = container.get_connection_url()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(settings, "DATABASE_URL", url)

        cfg = Config(str(ALEMBIC_INI))
        command.upgrade(cfg, "head")

        # RLS — mesmo com FORCE — nunca se aplica a um superusuário (ver
        # https://www.postgresql.org/docs/current/ddl-rowsecurity.html:
        # "row security is always disabled for superusers... unless
        # explicitly noted"). O usuário criado pelo testcontainers pra
        # rodar as migrations É o superuser do cluster efêmero — pra
        # validar RLS de verdade, um role de aplicação restrito (LOGIN,
        # sem BYPASSRLS) precisa DONO das tabelas escopadas (simula o role
        # real de produção, que tipicamente possui as próprias tabelas —
        # exatamente por isso a migration usa FORCE) roda as queries reais
        # dos testes, nunca o superuser usado só pra montar o schema.
        engine_superuser = create_engine(url)
        with engine_superuser.begin() as conn:
            conn.execute(text("CREATE ROLE app_role LOGIN PASSWORD 'app_role'"))
            conn.execute(text("GRANT ALL ON ALL TABLES IN SCHEMA public TO app_role"))
            conn.execute(text("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO app_role"))
            for tabela in _TABELAS_COM_RLS:
                conn.execute(text(f"ALTER TABLE {tabela} OWNER TO app_role"))
        engine_superuser.dispose()

        url_app_role = make_url(url).set(username="app_role", password="app_role")
        engine = create_engine(url_app_role)
        yield engine
        engine.dispose()
        monkeypatch.undo()
    finally:
        container.stop()


@pytest.fixture
def duas_lojas_com_torneio(pg_engine: Engine) -> dict:
    """Cria, direto via SQL, duas lojas independentes com um torneio cada —
    o cenário mínimo pra provar que a policy de RLS isola uma loja da
    outra. Usa `SET LOCAL app.current_loja_id` antes de cada insert pra que
    o próprio INSERT já respeite a policy (WITH CHECK) em vez de precisar
    de um bypass de superusuário.

    Sufixo aleatório em email/slug/id: `pg_engine` é escopo de sessão (o
    container Postgres é caro pra subir, reaproveitado por todos os testes
    do módulo) mas esta fixture roda de novo a cada teste — sem um sufixo
    único, o segundo teste bateria de frente com dados do primeiro (mesmo
    email, mesmo slug, mesma unique constraint)."""
    sufixo = uuid.uuid4().hex[:8]

    with pg_engine.begin() as conn:
        dados = {}
        for chave, nome in (("a", "Loja Isolamento A"), ("b", "Loja Isolamento B")):
            usuario_id = conn.execute(text(
                "INSERT INTO usuario (email, is_active, data_cadastro, tipo, senha) "
                "VALUES (:email, true, now(), 'loja', 'x') RETURNING id"
            ), {"email": f"loja.isolamento.{chave}.{sufixo}@gmail.com"}).scalar_one()

            loja_id = conn.execute(text(
                "INSERT INTO loja (nome, usuario_id, status, slug) "
                "VALUES (:nome, :usuario_id, 'APROVADA', :slug) RETURNING id"
            ), {"nome": nome, "usuario_id": usuario_id, "slug": f"loja-isolamento-{chave}-{sufixo}"}).scalar_one()

            conn.execute(text("SET LOCAL app.current_loja_id = :loja_id"), {"loja_id": loja_id})
            torneio_id = f"torneio-isolamento-{chave}-{sufixo}"
            conn.execute(text(
                "INSERT INTO torneio (id, loja_id, jogo, melhor_de, tipo, data_planejada, "
                "vagas, tempo_por_rodada, n_rodadas, rodada_atual, taxa, pontuacao_de_participacao) "
                "VALUES (:id, :loja_id, 'POKEMON', 'MD1', 'CRIADO', '2026-08-01', 8, 30, 0, 0, 0, 0)"
            ), {"id": torneio_id, "loja_id": loja_id})

            dados[chave] = {"loja_id": loja_id, "torneio_id": torneio_id}

    return dados
