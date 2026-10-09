"""Contratos do Conta Azul (servicos contratados) por cliente.

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    if "client_contracts" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("client_contracts",
                        sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("ext_id", sa.String(64), nullable=False, unique=True),
                        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True),
                        sa.Column("person_id", sa.String(64), index=True),
                        sa.Column("number", sa.Integer),
                        sa.Column("status", sa.String(16)),
                        sa.Column("description", sa.Text),
                        sa.Column("start_date", sa.Date),
                        sa.Column("end_date", sa.Date),
                        sa.Column("synced_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_table("client_contracts")
