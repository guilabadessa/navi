"""Regras de alerta por origem (infra, backup, endpoint, cloud).

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    if "kinds" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("alert_rules")}:
        op.add_column("alert_rules", sa.Column("kinds", sa.JSON))


def downgrade():
    op.drop_column("alert_rules", "kinds")
