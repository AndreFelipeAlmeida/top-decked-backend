"""rls_tabelas_escopadas_por_loja

Revision ID: 26624c2acb3b
Revises: 4654527c75e0
Create Date: 2026-07-13 23:06:33.115589

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '26624c2acb3b'
down_revision: Union[str, Sequence[str], None] = '4654527c75e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABELAS_NOT_NULL = ("jogadortorneiolink", "rodada", "pontuacaoextra", "temporada", "evento")
# loja_id nullable no schema atual — uma regra (TipoJogador) ou torneio sem
# loja_id não pode virar invisível pra todo mundo (NULL = X nunca é
# verdadeiro em SQL), por isso a policy permite explicitamente NULL passar.
_TABELAS_NULLABLE = ("torneio", "tipojogador")

_VARIAVEL_SESSAO = "app.current_loja_id"


def _condicao(tabela: str) -> str:
    # NULLIF(..., '') é necessário: current_setting(x, true) numa sessão
    # que nunca deu SET em x pode voltar '' (string vazia), não NULL —
    # ''::integer explode com "invalid input syntax for type integer".
    # Descoberto rodando esta suíte contra Postgres de verdade (SQLite não
    # tem current_setting pra pegar esse caso na suíte principal).
    igualdade = f"loja_id = NULLIF(current_setting('{_VARIAVEL_SESSAO}', true), '')::integer"
    if tabela in _TABELAS_NULLABLE:
        return f"({igualdade} OR loja_id IS NULL)"
    return igualdade


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        # RLS é recurso nativo do Postgres — SQLite (dev/teste, ver
        # tests/conftest.py) não tem esse conceito. A garantia de
        # isolamento por loja em dev/teste continua vindo inteiramente da
        # camada de aplicação (verificar_permissao_gerenciar_torneio etc.);
        # RLS aqui é "defesa em profundidade" específica de produção,
        # validada pela suíte separada em tests/postgres_isolation/ (roda
        # contra um Postgres efêmero de verdade, não SQLite).
        return

    for tabela in (*_TABELAS_NOT_NULL, *_TABELAS_NULLABLE):
        condicao = _condicao(tabela)
        conn.execute(sa.text(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY"))
        # FORCE é necessário porque o usuário de aplicação no Postgres
        # tipicamente é o DONO da tabela — sem FORCE, RLS não se aplica ao
        # dono, o que anularia a proteção pra exatamente quem faz as
        # queries de verdade.
        conn.execute(sa.text(f"ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"""
            CREATE POLICY policy_{tabela}_isolamento_loja ON {tabela}
            USING ({condicao})
            WITH CHECK ({condicao})
        """))


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    for tabela in (*_TABELAS_NOT_NULL, *_TABELAS_NULLABLE):
        conn.execute(sa.text(f"DROP POLICY IF EXISTS policy_{tabela}_isolamento_loja ON {tabela}"))
        conn.execute(sa.text(f"ALTER TABLE {tabela} NO FORCE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"ALTER TABLE {tabela} DISABLE ROW LEVEL SECURITY"))
