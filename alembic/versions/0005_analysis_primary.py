"""analyses.primary_at column, the version in use mark

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE analyses ADD COLUMN primary_at BIGINT;")
    op.execute("UPDATE app_meta SET value = '5' WHERE key = 'schema_version';")


def downgrade() -> None:
    op.execute("ALTER TABLE analyses DROP COLUMN primary_at;")
    op.execute("UPDATE app_meta SET value = '4' WHERE key = 'schema_version';")
