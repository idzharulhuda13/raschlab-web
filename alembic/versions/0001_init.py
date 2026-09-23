"""init

Revision ID: 0001
Revises:
Create Date: 2026-09-23 20:34:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_meta",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )
    op.execute(
        sa.text("INSERT INTO app_meta (key, value) VALUES (:key, :value)").bindparams(
            key="schema_version",
            value="1",
        )
    )


def downgrade() -> None:
    op.drop_table("app_meta")
