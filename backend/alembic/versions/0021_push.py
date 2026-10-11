"""Notificacoes push (Web Push) para o app.

Revision ID: 0021
Revises: 0020
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "push_subs" not in have:
        op.create_table("push_subs",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
            sa.Column("endpoint", sa.String(1024), unique=True),
            sa.Column("p256dh", sa.String(255)), sa.Column("auth", sa.String(64)), sa.Column("ua", sa.String(255)),
            sa.Column("created_at", sa.DateTime(timezone=True)), sa.Column("last_ok", sa.DateTime(timezone=True)))
    if "push_sent" not in have:
        op.create_table("push_sent",
            sa.Column("event_id", sa.BigInteger, sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("sent_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_table("push_sent")
    op.drop_table("push_subs")
