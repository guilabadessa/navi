"""Silenciar alertas pela tela de Eventos.

Revision ID: 0033
Revises: 0032
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_silences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(12)),
        sa.Column("host", sa.String(255)),
        sa.Column("triggerid", sa.String(64)),
        sa.Column("trigger_name", sa.String(1024)),
        sa.Column("until", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.String(255)),
        sa.Column("asset_id", sa.Integer()),
        sa.Column("created_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_event_silences_host", "event_silences", ["host"])
    op.create_index("ix_event_silences_until", "event_silences", ["until"])


def downgrade():
    op.drop_table("event_silences")
