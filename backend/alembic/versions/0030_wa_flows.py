"""Fluxo de atendimento editavel (BPMN) e estado do fluxo nas conversas.

Revision ID: 0030
Revises: 0029
"""
import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wa_flows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("wa_conversations", sa.Column("flow_node", sa.String(64)))
    op.add_column("wa_conversations", sa.Column("flow_vars", sa.JSON()))


def downgrade():
    op.drop_column("wa_conversations", "flow_vars")
    op.drop_column("wa_conversations", "flow_node")
    op.drop_table("wa_flows")
