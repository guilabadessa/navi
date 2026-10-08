"""Avisos opcionais ao cliente: boleto a vencer e resumo mensal.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("clients")}
    for n in ("notify_boleto", "notify_monthly"):
        if n not in cols:
            op.add_column("clients", sa.Column(n, sa.Boolean(), nullable=False, server_default=sa.false()))
    if "fin_notices" not in insp.get_table_names():
        op.create_table("fin_notices",
                        sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
                        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="CASCADE"), index=True, nullable=False),
                        sa.Column("kind", sa.String(16), nullable=False), sa.Column("ref", sa.String(64), nullable=False),
                        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
                        sa.UniqueConstraint("user_id", "kind", "ref"))


def downgrade():
    pass
