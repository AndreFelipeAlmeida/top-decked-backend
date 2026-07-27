"""ondelete set null jogador_id (jogadorcriado, historicocredito, transacao)

Revision ID: d632edd998c3
Revises: d66eed1e1528
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd632edd998c3'
down_revision: Union[str, Sequence[str], None] = 'd66eed1e1528'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Os três FKs foram criados sem nome explícito na migration baseline
# (sa.ForeignKeyConstraint(['jogador_id'], ['jogador.id'])), então nem
# SQLite nem o model em si têm um nome pra referenciar -- a convenção abaixo
# só existe pra dar um nome à constraint reflectida na hora de trocá-la
# (batch mode, funciona igual em SQLite e Postgres).
_TABELAS = ("jogadorcriado", "historicocredito", "transacao")
_NAMING_CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade() -> None:
    for tabela in _TABELAS:
        nome_constraint = f"fk_{tabela}_jogador_id_jogador"
        with op.batch_alter_table(tabela, schema=None, naming_convention=_NAMING_CONVENTION) as batch_op:
            batch_op.drop_constraint(nome_constraint, type_="foreignkey")
            batch_op.create_foreign_key(nome_constraint, "jogador", ["jogador_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    for tabela in _TABELAS:
        nome_constraint = f"fk_{tabela}_jogador_id_jogador"
        with op.batch_alter_table(tabela, schema=None, naming_convention=_NAMING_CONVENTION) as batch_op:
            batch_op.drop_constraint(nome_constraint, type_="foreignkey")
            batch_op.create_foreign_key(nome_constraint, "jogador", ["jogador_id"], ["id"])
