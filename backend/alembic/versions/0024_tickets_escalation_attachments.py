"""Chamados: escalonamento (lembrete de 24h sem resposta) e anexos.

Revision ID: 0024
Revises: 0023
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tickets", sa.Column("escalated_at", sa.DateTime(timezone=True)))
    op.create_table(
        "ticket_attachments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.BigInteger, sa.ForeignKey("ticket_messages.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("stored_path", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(120)),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_attachments_ticket_id", "ticket_attachments", ["ticket_id"])


def downgrade():
    op.drop_table("ticket_attachments")
    op.drop_column("tickets", "escalated_at")
