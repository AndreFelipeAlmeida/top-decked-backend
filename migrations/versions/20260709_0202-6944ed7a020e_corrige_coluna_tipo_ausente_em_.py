"""corrige coluna tipo ausente em jogadortorneiolink

Revision ID: 6944ed7a020e
Revises: f0256c9944ef
Create Date: 2026-07-09 02:02:31.327991

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '6944ed7a020e'
down_revision: Union[str, Sequence[str], None] = 'f0256c9944ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# `ba9d81184506` faz `create_table('pontuacaoextra')` (tabela nova) e
# `add_column('tipo', ...)` em `jogadortorneiolink` (coluna nova numa tabela
# JÁ EXISTENTE) na MESMA migration. `create_all()` (bootstrap de dev, ver
# app/core/db.py) cria tabelas que faltam mas nunca altera uma tabela já
# existente — então, se o deploy que introduziu `PontuacaoExtra` já rodou em
# produção antes do Alembic existir (mesma raiz do item 74/f0256c9944ef),
# `pontuacaoextra` pode já existir (tabela nova, `create_all` criou), mas
# `jogadortorneiolink.tipo` nunca foi adicionada (coluna nova em tabela
# existente, fora do alcance de `create_all`) — e ao adotar o Alembic num
# banco assim, quem for stampar a revisão correta pra pular a criação de
# `pontuacaoextra` (que já existe) acaba pulando o `add_column('tipo')`
# junto, silenciosamente, mesmo a coluna nunca tendo sido criada de verdade.
#
# Esta migration tampa esse buraco do mesmo jeito defensivo de f0256c9944ef:
# só adiciona a coluna se ela realmente não existir — no-op em qualquer banco
# onde `ba9d81184506` já rodou de verdade (dev, teste, produção adotada do
# zero via baseline).
def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    colunas = {c["name"] for c in sa.inspect(conn).get_columns("jogadortorneiolink")}

    if "tipo" not in colunas:
        with op.batch_alter_table("jogadortorneiolink", schema=None) as batch_op:
            batch_op.add_column(sa.Column(
                "tipo",
                sa.Enum("JOGADOR", "JUIZ", name="tipoparticipantetorneio"),
                nullable=False,
                server_default="JOGADOR",
            ))


def downgrade() -> None:
    """Downgrade schema."""
    # No-op de propósito, mesmo raciocínio de f0256c9944ef — a correção só
    # faz algo em bancos onde `ba9d81184506` nunca chegou a adicionar a
    # coluna; não há como diferenciar esse caso de dentro de downgrade() sem
    # guardar estado extra, e essa migration nunca deveria ser desfeita (é
    # uma correção de dado legado, não uma feature).
    pass
