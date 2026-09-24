"""datasets table

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE datasets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,
    format TEXT NOT NULL,
    status TEXT NOT NULL,
    n_persons INTEGER NOT NULL,
    n_items INTEGER NOT NULL,
    item_labels_json TEXT NOT NULL,
    mapping_json TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    raw_gzip BYTEA NOT NULL,
    raw_bytes BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    committed_at BIGINT
);"""
    )
    op.execute("CREATE INDEX ix_datasets_user_id ON datasets (user_id);")
    op.execute("UPDATE app_meta SET value = '3' WHERE key = 'schema_version';")


def downgrade() -> None:
    op.execute("DROP TABLE datasets;")
    op.execute("UPDATE app_meta SET value = '2' WHERE key = 'schema_version';")
