"""auth tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    email_normalized TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    verified_at BIGINT
);"""
    )
    op.execute("CREATE UNIQUE INDEX uq_users_email_normalized ON users (email_normalized);")
    op.execute(
        """CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL
);"""
    )
    op.execute("CREATE UNIQUE INDEX uq_sessions_token_hash ON sessions (token_hash);")
    op.execute("CREATE INDEX ix_sessions_user_id ON sessions (user_id);")
    op.execute(
        """CREATE TABLE email_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    used_at BIGINT
);"""
    )
    op.execute("CREATE UNIQUE INDEX uq_email_tokens_token_hash ON email_tokens (token_hash);")
    op.execute("CREATE INDEX ix_email_tokens_user_purpose ON email_tokens (user_id, purpose);")
    op.execute("UPDATE app_meta SET value = '2' WHERE key = 'schema_version';")


def downgrade() -> None:
    op.execute("DROP TABLE email_tokens;")
    op.execute("DROP TABLE sessions;")
    op.execute("DROP TABLE users;")
    op.execute("UPDATE app_meta SET value = '1' WHERE key = 'schema_version';")
