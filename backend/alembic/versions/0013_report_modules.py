"""Relatorio com modulos selecionaveis (infraestrutura, backup, estacoes).

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    if "modules" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("reports")}:
        op.add_column("reports", sa.Column("modules", sa.JSON))


def downgrade():
    op.drop_column("reports", "modules")
