"""loja_slug

Revision ID: 4654527c75e0
Revises: 558062a78681
Create Date: 2026-07-13 11:16:03.100340

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

from app.utils.SlugUtil import slugify


# revision identifiers, used by Alembic.
revision: str = '4654527c75e0'
down_revision: Union[str, Sequence[str], None] = '558062a78681'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    colunas = {c["name"] for c in sa.inspect(conn).get_columns("loja")}
    if "slug" not in colunas:
        with op.batch_alter_table("loja", schema=None) as batch_op:
            batch_op.add_column(sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    # Passo 2: backfill — slugify(nome) + sufixo numérico determinístico em
    # caso de colisão. Processado em Python (não dá pra fazer só com SQL) e
    # em memória (poucas lojas por natureza do negócio — uma por
    # estabelecimento real).
    lojas = conn.execute(sa.text("SELECT id, nome, slug FROM loja")).fetchall()
    slugs_ja_usados: set[str] = {loja.slug for loja in lojas if loja.slug}

    for loja in lojas:
        if loja.slug:
            continue
        base = slugify(loja.nome)
        slug = base
        sufixo = 2
        while slug in slugs_ja_usados:
            slug = f"{base}-{sufixo}"
            sufixo += 1
        slugs_ja_usados.add(slug)
        conn.execute(
            sa.text("UPDATE loja SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": loja.id},
        )

    # Passo 3: unique index — defensivo, mesmo motivo do passo 1.
    indices_existentes = {idx["name"] for idx in sa.inspect(conn).get_indexes("loja")}
    if "ix_loja_slug" not in indices_existentes:
        with op.batch_alter_table("loja", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_loja_slug"), ["slug"], unique=True)

    # Passo 4: NOT NULL — defensivo, mesmo motivo do passo 1.
    coluna_slug = next(c for c in sa.inspect(conn).get_columns("loja") if c["name"] == "slug")
    if coluna_slug["nullable"]:
        with op.batch_alter_table("loja", schema=None) as batch_op:
            batch_op.alter_column("slug", existing_type=sqlmodel.sql.sqltypes.AutoString(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("loja", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_loja_slug"))
        batch_op.drop_column("slug")
