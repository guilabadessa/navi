"""WhatsApp: mensagens recebidas/enviadas pelo gateway (WA-AKG).

Revision ID: 0028
Revises: 0027
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wa_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("external_id", sa.String(128), nullable=False, unique=True),
        sa.Column("session", sa.String(64), nullable=False),
        sa.Column("jid", sa.String(128), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("type", sa.String(24), nullable=False, server_default="TEXT"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_ref", sa.String(512)),
        sa.Column("push_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_wa_messages_jid", "wa_messages", ["jid"])
    op.create_index("ix_wa_messages_created_at", "wa_messages", ["created_at"])


def downgrade():
    op.drop_table("wa_messages")
