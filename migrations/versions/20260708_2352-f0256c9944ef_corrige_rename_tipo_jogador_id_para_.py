"""corrige rename tipo_jogador_id para regra_extra_id em bancos pre-existentes

Revision ID: f0256c9944ef
Revises: 28947b4e7a24
Create Date: 2026-07-08 23:52:39.849017

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0256c9944ef'
down_revision: Union[str, Sequence[str], None] = '28947b4e7a24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# `JogadorTorneioLink.tipo_jogador_id` virou `regra_extra_id` (ver
# docs/REGRA_EXTRA.md, item 70 de docs/DIVIDA_TECNICA.md) num rename de
# model feito ANTES do Alembic existir neste projeto — a migration baseline
# (a5f913d8cd90) já cria `jogadortorneiolink` com `regra_extra_id` do zero,
# porque foi gerada por autogenerate contra um banco vazio, comparando com o
# estado do model NAQUELE momento (que já estava com o nome novo). Isso
# funciona bem pra bancos criados a partir do zero (dev/teste), mas deixa um
# buraco pra qualquer banco que já existia ANTES dessa rodada — com
# `tipo_jogador_id` de verdade, sem nenhuma migration aplicada — e nunca
# passou por um `ALTER TABLE ... RENAME COLUMN`.
#
# Esta migration tampa esse buraco de forma defensiva: só renomeia se
# encontrar a coluna antiga E não encontrar a nova — em qualquer banco criado
# a partir da baseline (dev, teste, ou produção zerada), isso não faz nada.
def _renomear_coluna(de: str, para: str) -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    colunas = {c["name"] for c in inspector.get_columns("jogadortorneiolink")}

    if de in colunas and para not in colunas:
        with op.batch_alter_table("jogadortorneiolink", schema=None) as batch_op:
            batch_op.alter_column(de, new_column_name=para)


def upgrade() -> None:
    """Upgrade schema."""
    _renomear_coluna("tipo_jogador_id", "regra_extra_id")


def downgrade() -> None:
    """Downgrade schema."""
    # De propósito um no-op, não o rename espelhado. Essa correção só faz
    # algo em bancos legados (que tinham tipo_jogador_id); num banco criado
    # a partir da baseline, upgrade() já é um no-op — então "desfazer" com o
    # rename inverso quebraria justamente os bancos onde upgrade() nunca
    # tinha mexido em nada, trocando um regra_extra_id correto de volta pro
    # nome antigo que o resto do código (models.py, rotas) não reconhece
    # mais. Não há como distinguir os dois casos de dentro de downgrade()
    # sem guardar estado extra, e essa migration nunca deveria ser desfeita
    # de qualquer forma (é uma correção de dado legado, não uma feature).
    pass
