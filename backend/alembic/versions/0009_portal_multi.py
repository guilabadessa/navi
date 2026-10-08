"""Portal: severidade minima por usuario e usuario com varios clientes.

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if "portal_min_sev" not in {c["name"] for c in insp.get_columns("users")}:
        op.add_column("users", sa.Column("portal_min_sev", sa.Integer(), nullable=False, server_default="4"))
    if "user_clients" not in insp.get_table_names():
        op.create_table("user_clients",
                        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
                        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True, index=True))


def downgrade():
    pass
