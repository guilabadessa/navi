"""Chamados (helpdesk): filas por tecnologia, chamados, observadores (CC) e mensagens.

Revision ID: 0023
Revises: 0022
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ticket_queues",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("notify_emails", sa.Text),
        sa.Column("notify_wa_jid", sa.String(128)),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("number", sa.Integer, nullable=False, unique=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("queue_id", sa.Integer, sa.ForeignKey("ticket_queues.id")),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="aberto"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="media"),
        sa.Column("origin", sa.String(16), nullable=False, server_default="staff"),
        sa.Column("created_by_id", sa.Integer),
        sa.Column("created_by_name", sa.String(255)),
        sa.Column("assigned_to_id", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tickets_client_id", "tickets", ["client_id"])
    op.create_index("ix_tickets_status", "tickets", ["status"])
    op.create_index("ix_tickets_number", "tickets", ["number"], unique=True)
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])

    op.create_table(
        "ticket_watchers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("label", sa.String(120)),
    )
    op.create_index("ix_ticket_watchers_ticket_id", "ticket_watchers", ["ticket_id"])

    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer),
        sa.Column("author_name", sa.String(255)),
        sa.Column("origin", sa.String(16), nullable=False, server_default="staff"),
        sa.Column("internal", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("notified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_messages_ticket_id", "ticket_messages", ["ticket_id"])
    op.create_index("ix_ticket_messages_created_at", "ticket_messages", ["created_at"])


def downgrade():
    op.drop_table("ticket_messages")
    op.drop_table("ticket_watchers")
    op.drop_table("tickets")
    op.drop_table("ticket_queues")
