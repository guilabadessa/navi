"""Itens (servicos) dos contratos do Conta Azul.

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    if "items" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("client_contracts")}:
        op.add_column("client_contracts", sa.Column("items", sa.JSON))


def downgrade():
    op.drop_column("client_contracts", "items")
