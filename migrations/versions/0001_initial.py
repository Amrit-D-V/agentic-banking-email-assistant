"""initial schema

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email_id", sa.String(64), nullable=False, index=True),
        sa.Column("timestamp", sa.String(32), nullable=False, index=True),
        sa.Column("payload", sa.Text, nullable=False),
    )
    op.create_table(
        "review_items",
        sa.Column("email_id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("queued_at", sa.String(32), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
    )
    op.create_table(
        "runtime_config",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    op.create_table(
        "processed_messages",
        sa.Column("message_id", sa.String(255), primary_key=True),
        sa.Column("email_id", sa.String(64), nullable=False),
        sa.Column("processed_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "failed_emails",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.String(255), index=True),
        sa.Column("failed_at", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
    )


def downgrade() -> None:
    for table in ("failed_emails", "processed_messages", "runtime_config", "review_items", "audit_records"):
        op.drop_table(table)
