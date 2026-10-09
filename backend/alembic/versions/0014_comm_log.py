"""Historico de comunicacoes que nao sao alertas (relatorios, resumo, avisos, testes, convites) e suas falhas.

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    if "comm_log" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("comm_log",
                        sa.Column("id", sa.BigInteger, primary_key=True),
                        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
                        sa.Column("channel", sa.String(16), nullable=False, index=True),
                        sa.Column("kind", sa.String(48), nullable=False),
                        sa.Column("dest", sa.Text),
                        sa.Column("subject", sa.String(300)),
                        sa.Column("status", sa.String(16), nullable=False),
                        sa.Column("error", sa.Text),
                        sa.Column("client_id", sa.Integer, index=True))


def downgrade():
    op.drop_table("comm_log")
