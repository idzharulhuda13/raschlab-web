"""analyses and analysis_files tables, dataset matrix_gzip column

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE datasets ADD COLUMN matrix_gzip BYTEA;")
    op.execute(
        """CREATE TABLE analyses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    dataset_id INTEGER NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    params_json TEXT NOT NULL,
    engine_ref TEXT NOT NULL,
    error TEXT,
    elapsed_ms INTEGER,
    created_at BIGINT NOT NULL,
    started_at BIGINT,
    finished_at BIGINT,
    expires_at BIGINT NOT NULL,
    notice_sent_at BIGINT
);"""
    )
    op.execute("CREATE INDEX ix_analyses_user_id ON analyses (user_id);")
    op.execute("CREATE INDEX ix_analyses_dataset_id ON analyses (dataset_id);")
    op.execute("CREATE INDEX ix_analyses_expires_at ON analyses (expires_at);")
    op.execute(
        """CREATE TABLE analysis_files (
    id SERIAL PRIMARY KEY,
    analysis_id INTEGER NOT NULL REFERENCES analyses (id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_gzip BYTEA NOT NULL,
    sha256 TEXT NOT NULL,
    bytes BIGINT NOT NULL,
    UNIQUE (analysis_id, filename)
);"""
    )
    op.execute("CREATE INDEX ix_analysis_files_analysis_id ON analysis_files (analysis_id);")
    op.execute("UPDATE app_meta SET value = '4' WHERE key = 'schema_version';")


def downgrade() -> None:
    op.execute("DROP TABLE analysis_files;")
    op.execute("DROP TABLE analyses;")
    op.execute("ALTER TABLE datasets DROP COLUMN matrix_gzip;")
    op.execute("UPDATE app_meta SET value = '3' WHERE key = 'schema_version';")
