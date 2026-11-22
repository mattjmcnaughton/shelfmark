"""To try queue: optional item URLs, try_at, and notes

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.alter_column("url", existing_type=sa.String(2048), nullable=True)
        batch.add_column(
            sa.Column("note", sa.String(2000), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("try_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.execute("DELETE FROM items WHERE url IS NULL")
    with op.batch_alter_table("items") as batch:
        batch.drop_column("try_at")
        batch.drop_column("note")
        batch.alter_column("url", existing_type=sa.String(2048), nullable=False)
