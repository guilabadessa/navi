"""Atendimento por WhatsApp: conversas e vinculo das mensagens.

Revision ID: 0029
Revises: 0028
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wa_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("jid", sa.String(128), nullable=False),
        sa.Column("push_name", sa.String(255)),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL")),
        sa.Column("queue", sa.String(16), nullable=False, server_default="geral"),
        sa.Column("state", sa.String(16), nullable=False, server_default="menu"),
        sa.Column("assigned_to", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("menu_sent_at", sa.DateTime(timezone=True)),
        sa.Column("menu_tries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queued_at", sa.DateTime(timezone=True)),
        sa.Column("assumed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("unread", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_wa_conversations_jid", "wa_conversations", ["jid"])
    op.create_index("ix_wa_conversations_state", "wa_conversations", ["state"])
    op.create_index("ix_wa_conversations_client_id", "wa_conversations", ["client_id"])
    op.add_column("wa_messages", sa.Column("conversation_id", sa.BigInteger(), sa.ForeignKey("wa_conversations.id", ondelete="SET NULL")))
    op.add_column("wa_messages", sa.Column("sent_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.add_column("wa_messages", sa.Column("failed", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_wa_messages_conversation_id", "wa_messages", ["conversation_id"])


def downgrade():
    op.drop_index("ix_wa_messages_conversation_id", "wa_messages")
    op.drop_column("wa_messages", "failed")
    op.drop_column("wa_messages", "sent_by")
    op.drop_column("wa_messages", "conversation_id")
    op.drop_table("wa_conversations")
