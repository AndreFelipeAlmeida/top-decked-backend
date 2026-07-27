"""ondelete set null jogador_id (jogadorcriado, historicocredito, transacao)

Revision ID: d632edd998c3
Revises: d66eed1e1528
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd632edd998c3'
down_revision: Union[str, Sequence[str], None] = 'd66eed1e1528'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Os três FKs foram criados sem nome explícito na migration baseline
# (sa.ForeignKeyConstraint(['jogador_id'], ['jogador.id'])) -- cada dialeto
# reage diferente a isso: o Postgres atribui um nome automático próprio
# (`<tabela>_jogador_id_fkey`) já na criação da tabela, enquanto o SQLite
# reflete a constraint sem nome nenhum (None). Por isso descobrimos o nome
# de verdade em tempo de execução em vez de adivinhar um fixo -- adivinhar
# funcionava no SQLite (onde batch mode recria a tabela do zero e só usa o
# nome pra bookkeeping interno) mas quebrava no Postgres (onde o
# drop_constraint vira um ALTER TABLE direto, que exige o nome exato já
# existente no banco).
_TABELAS = ("jogadorcriado", "historicocredito", "transacao")
_NAMING_CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _nome_fk_jogador_id(bind, tabela: str) -> str | None:
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys(tabela):
        if fk.get("referred_table") == "jogador" and fk.get("constrained_columns") == ["jogador_id"]:
            return fk.get("name")
    return None


def _alterar_ondelete(tabela: str, ondelete: str | None) -> None:
    bind = op.get_bind()
    nome_real = _nome_fk_jogador_id(bind, tabela)
    # Nome real encontrado (Postgres, ou SQLite já rodado uma vez por esta
    # migration) -> usamos ele. Sem nome real (SQLite "cru", reflete None)
    # -> convenção só pra dar um nome de referência à recriação em batch.
    nome_constraint = nome_real or f"fk_{tabela}_jogador_id_jogador"
    naming_convention = None if nome_real else _NAMING_CONVENTION

    with op.batch_alter_table(tabela, schema=None, naming_convention=naming_convention) as batch_op:
        batch_op.drop_constraint(nome_constraint, type_="foreignkey")
        batch_op.create_foreign_key(nome_constraint, "jogador", ["jogador_id"], ["id"], ondelete=ondelete)


def upgrade() -> None:
    for tabela in _TABELAS:
        _alterar_ondelete(tabela, "SET NULL")


def downgrade() -> None:
    for tabela in _TABELAS:
        _alterar_ondelete(tabela, None)
