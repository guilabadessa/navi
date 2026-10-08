"""Regras de reclassificacao de severidade.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    if "severity_rules" in sa.inspect(op.get_bind()).get_table_names():
        return  # instalacao nova: o baseline ja criou
    op.create_table(
        "severity_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("host_pattern", sa.String(255)),
        sa.Column("trigger_pattern", sa.String(255)),
        sa.Column("from_max", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    pass
