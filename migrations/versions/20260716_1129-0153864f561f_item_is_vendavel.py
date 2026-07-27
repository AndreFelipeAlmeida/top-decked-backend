"""item is_vendavel

Revision ID: 0153864f561f
Revises: 26624c2acb3b
Create Date: 2026-07-16 11:29:26.317084

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '0153864f561f'
down_revision: Union[str, Sequence[str], None] = '26624c2acb3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_vendavel', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('item', schema=None) as batch_op:
        batch_op.drop_column('is_vendavel')
