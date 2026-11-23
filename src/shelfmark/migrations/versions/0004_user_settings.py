"""Per-user settings and feed entries skipped at follow time

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("feed_backfill", sa.Integer(), server_default="3", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_settings")),
    )
    op.create_table(
        "feed_skipped_entries",
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.ForeignKeyConstraint(
            ["feed_id"],
            ["feeds.id"],
            name=op.f("fk_feed_skipped_entries_feed_id_feeds"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("feed_id", "url", name=op.f("pk_feed_skipped_entries")),
    )


def downgrade() -> None:
    op.drop_table("feed_skipped_entries")
    op.drop_table("user_settings")
