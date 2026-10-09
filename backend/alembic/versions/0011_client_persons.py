"""Varios cadastros (CNPJs) do Conta Azul por cliente.

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    if "client_persons" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("client_persons",
                        sa.Column("person_id", sa.String(64), primary_key=True),
                        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True),
                        sa.Column("match", sa.String(16), nullable=False, server_default="manual"))
        op.execute("INSERT INTO client_persons (person_id, client_id, match) SELECT ca_person_id, id, COALESCE(ca_match, 'manual') "
                   "FROM clients WHERE ca_person_id IS NOT NULL ON CONFLICT DO NOTHING")


def downgrade():
    pass
