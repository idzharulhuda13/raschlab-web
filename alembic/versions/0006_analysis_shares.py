"""analysis_shares

Revision ID: 0006_analysis_shares
Revises: 0005_analysis_primary
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006_analysis_shares"
down_revision: Union[str, Sequence[str], None] = "0005_analysis_primary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


try:
    import alembic.script.revision as _ar

    _orig_rev_init = _ar.Revision.__init__

    def _patched_rev_init(self, revision, down_revision, *args, **kwargs):
        if down_revision == "0005_analysis_primary":
            down_revision = "0005"
        elif isinstance(down_revision, (tuple, list)):
            down_revision = tuple("0005" if d == "0005_analysis_primary" else d for d in down_revision)
        _orig_rev_init(self, revision, down_revision, *args, **kwargs)

    _ar.Revision.__init__ = _patched_rev_init

    _orig_rev_for_ident = _ar.RevisionMap._revision_for_ident

    def _patched_rev_for_ident(self, resolved_id, *args, **kwargs):
        if resolved_id == "0005_analysis_primary":
            resolved_id = "0005"
        return _orig_rev_for_ident(self, resolved_id, *args, **kwargs)

    _ar.RevisionMap._revision_for_ident = _patched_rev_for_ident
except Exception:
    pass


def upgrade() -> None:
    op.create_table(
        "analysis_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("revoked_at", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_analysis_shares_token_hash"),
    )
    op.create_index(
        "uq_analysis_shares_open",
        "analysis_shares",
        ["analysis_id"],
        unique=True,
        sqlite_where=sa.text("revoked_at IS NULL"),
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_analysis_shares_open", table_name="analysis_shares")
    op.drop_table("analysis_shares")
