"""rls bypass leitura publica

Revision ID: 12bfeafce680
Revises: 0153864f561f
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12bfeafce680'
down_revision: Union[str, Sequence[str], None] = '0153864f561f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VARIAVEL_TENANT = "app.current_loja_id"
_VARIAVEL_LEITURA_PUBLICA = "app.leitura_publica"

_TABELAS_NOT_NULL = ("jogadortorneiolink", "rodada", "evento")
_TABELAS_NULLABLE = ("torneio",)

_BYPASS = f"current_setting('{_VARIAVEL_LEITURA_PUBLICA}', true) = 'on'"


def _condicao_com_bypass(tabela: str) -> str:
    igualdade = f"loja_id = NULLIF(current_setting('{_VARIAVEL_TENANT}', true), '')::integer"
    if tabela in _TABELAS_NULLABLE:
        return f"(({igualdade} OR loja_id IS NULL) OR {_BYPASS})"
    return f"({igualdade} OR {_BYPASS})"


def _condicao_sem_bypass(tabela: str) -> str:
    igualdade = f"loja_id = NULLIF(current_setting('{_VARIAVEL_TENANT}', true), '')::integer"
    if tabela in _TABELAS_NULLABLE:
        return f"({igualdade} OR loja_id IS NULL)"
    return igualdade


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    for tabela in (*_TABELAS_NOT_NULL, *_TABELAS_NULLABLE):
        conn.execute(sa.text(
            f"ALTER POLICY policy_{tabela}_isolamento_loja ON {tabela} "
            f"USING ({_condicao_com_bypass(tabela)})"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    for tabela in (*_TABELAS_NOT_NULL, *_TABELAS_NULLABLE):
        conn.execute(sa.text(
            f"ALTER POLICY policy_{tabela}_isolamento_loja ON {tabela} "
            f"USING ({_condicao_sem_bypass(tabela)})"
        ))
