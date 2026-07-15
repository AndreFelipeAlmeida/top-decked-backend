"""loja_id_denormalizado

Revision ID: 558062a78681
Revises: 75d688648a4b
Create Date: 2026-07-13 10:49:04.136077

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '558062a78681'
down_revision: Union[str, Sequence[str], None] = '75d688648a4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABELAS = ("jogadortorneiolink", "pontuacaoextra", "rodada")

_NOME_FUNCAO_TRIGGER = "brk304_verificar_loja_id_torneio"


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Passo 1: coluna nullable — um ADD COLUMN ... NOT NULL sem default
    # exigiria reescrever a tabela inteira na hora e falharia contra
    # qualquer linha já existente (BRK-304, nota técnica de migrations).
    # Defensivo (só adiciona o que ainda não existe) pelo mesmo motivo de
    # f0256c9944ef/6944ed7a020e: um banco que já tinha a coluna criada por
    # create_all() antes desta migration rodar de verdade não pode tentar
    # recriá-la.
    for tabela in _TABELAS:
        colunas = {c["name"] for c in inspector.get_columns(tabela)}
        if 'loja_id' in colunas:
            continue
        with op.batch_alter_table(tabela, schema=None) as batch_op:
            batch_op.add_column(sa.Column('loja_id', sa.Integer(), nullable=True))
            batch_op.create_index(batch_op.f(f'ix_{tabela}_loja_id'), ['loja_id'], unique=False)
            batch_op.create_foreign_key(batch_op.f(f'fk_{tabela}_loja_id_loja'), 'loja', ['loja_id'], ['id'])

    # Passo 2: backfill a partir do torneio pai (torneio_id -> torneio.loja_id).
    for tabela in _TABELAS:
        conn.execute(sa.text(
            f"UPDATE {tabela} SET loja_id = "
            f"(SELECT loja_id FROM torneio WHERE torneio.id = {tabela}.torneio_id)"
        ))

    # torneio.loja_id é nullable no schema atual (débito técnico anterior a
    # esta migration) — na prática todo torneio sempre tem uma loja (ver
    # TorneioService/criar_torneio), mas se algum registro legado realmente
    # não tiver, o backfill acima deixaria loja_id NULL e o passo 4 (NOT
    # NULL) quebraria com um erro genérico do banco. Falha explícita aqui é
    # melhor do que isso.
    for tabela in _TABELAS:
        orfaos = conn.execute(sa.text(
            f"SELECT COUNT(*) FROM {tabela} WHERE loja_id IS NULL"
        )).scalar()
        if orfaos:
            raise RuntimeError(
                f"{orfaos} linha(s) em '{tabela}' apontam pra um torneio sem loja_id — "
                "resolva esses dados manualmente antes de rodar esta migration."
            )

    # Passo 3: trigger de integridade — só Postgres (produção). SQLite não
    # tem PRAGMA foreign_keys habilitado neste projeto e a suíte de testes
    # roda nele; a garantia de integridade em dev/teste vem inteiramente da
    # aplicação (todo INSERT já passa loja_id=torneio.loja_id — ver
    # app/services/*.py). Ver docs/MULTI_TENANCY.md.
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text(f"""
            CREATE OR REPLACE FUNCTION {_NOME_FUNCAO_TRIGGER}() RETURNS trigger AS $$
            DECLARE
                loja_id_do_torneio integer;
            BEGIN
                SELECT loja_id INTO loja_id_do_torneio FROM torneio WHERE id = NEW.torneio_id;
                IF loja_id_do_torneio IS DISTINCT FROM NEW.loja_id THEN
                    RAISE EXCEPTION
                        'loja_id (%) diverge do loja_id (%) do torneio pai (%)',
                        NEW.loja_id, loja_id_do_torneio, NEW.torneio_id;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))

        for tabela in _TABELAS:
            conn.execute(sa.text(f"""
                CREATE TRIGGER trg_{tabela}_loja_id_integridade
                BEFORE INSERT OR UPDATE ON {tabela}
                FOR EACH ROW EXECUTE FUNCTION {_NOME_FUNCAO_TRIGGER}();
            """))

    # Passo 4: NOT NULL — defensivo pelo mesmo motivo do passo 1 (uma coluna
    # criada direto do model atual via create_all() já nasce NOT NULL).
    inspector = sa.inspect(conn)
    for tabela in _TABELAS:
        coluna_loja_id = next(c for c in inspector.get_columns(tabela) if c["name"] == "loja_id")
        if coluna_loja_id["nullable"]:
            with op.batch_alter_table(tabela, schema=None) as batch_op:
                batch_op.alter_column('loja_id', existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()

    if conn.dialect.name == "postgresql":
        for tabela in _TABELAS:
            conn.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{tabela}_loja_id_integridade ON {tabela}"))
        conn.execute(sa.text(f"DROP FUNCTION IF EXISTS {_NOME_FUNCAO_TRIGGER}()"))

    for tabela in _TABELAS:
        with op.batch_alter_table(tabela, schema=None) as batch_op:
            batch_op.drop_constraint(batch_op.f(f'fk_{tabela}_loja_id_loja'), type_='foreignkey')
            batch_op.drop_index(batch_op.f(f'ix_{tabela}_loja_id'))
            batch_op.drop_column('loja_id')
