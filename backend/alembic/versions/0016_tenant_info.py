"""Servicos contratados no Acronis (licencas/uso por tenant).

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    if "info" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ext_tenants")}:
        op.add_column("ext_tenants", sa.Column("info", sa.JSON))


def downgrade():
    op.drop_column("ext_tenants", "info")
