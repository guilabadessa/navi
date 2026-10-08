"""Convites/portal do cliente (users.client_id, invite_*) e janelas de manutencao.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("users")}
    if "client_id" not in cols:
        op.add_column("users", sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True))
        op.create_index("ix_users_client_id", "users", ["client_id"])
    if "invite_pending" not in cols:
        op.add_column("users", sa.Column("invite_pending", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "invited_at" not in cols:
        op.add_column("users", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))
    if "maintenance_windows" not in insp.get_table_names():
        op.create_table(
            "maintenance_windows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE")),
            sa.Column("kind", sa.String(8), nullable=False, server_default="once"),
            sa.Column("start_at", sa.DateTime(timezone=True)),
            sa.Column("end_at", sa.DateTime(timezone=True)),
            sa.Column("weekdays", sa.JSON()),
            sa.Column("start_time", sa.String(5)),
            sa.Column("duration_min", sa.Integer()),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.String(255)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_maintenance_windows_client_id", "maintenance_windows", ["client_id"])


def downgrade():
    pass
