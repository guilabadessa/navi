"""Chamados: chamado interno (so equipe, invisivel no portal e sem aviso) e unidade do cliente.

Revision ID: 0027
Revises: 0026
"""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tickets", sa.Column("internal", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("tickets", sa.Column("unit", sa.String(120)))
    op.create_index("ix_tickets_internal", "tickets", ["internal"])


def downgrade():
    op.drop_index("ix_tickets_internal", "tickets")
    op.drop_column("tickets", "unit")
    op.drop_column("tickets", "internal")
