"""jogadortorneiolink classificacao oficial

Revision ID: d66eed1e1528
Revises: 12bfeafce680
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd66eed1e1528'
down_revision: Union[str, Sequence[str], None] = '12bfeafce680'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('jogadortorneiolink', schema=None) as batch_op:
        batch_op.add_column(sa.Column('classificacao_oficial', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jogadortorneiolink', schema=None) as batch_op:
        batch_op.drop_column('classificacao_oficial')
