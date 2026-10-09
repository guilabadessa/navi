"""Nuvem Orca (BRASCLOUD): chave de API por cliente.

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    if "cloud_accounts" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("cloud_accounts",
                        sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True),
                        sa.Column("label", sa.String(255)),
                        sa.Column("api_key", sa.Text, nullable=False),
                        sa.Column("secret_key", sa.Text, nullable=False),
                        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
                        sa.Column("owner", sa.String(255)),
                        sa.Column("last_ok", sa.DateTime(timezone=True)),
                        sa.Column("last_error", sa.Text),
                        sa.Column("created_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_table("cloud_accounts")
