"""Integracoes Acronis/EMS: tenants e ativos externos; eventos com origem (kind).

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("events")}
    if "kind" not in cols:
        op.add_column("events", sa.Column("kind", sa.String(12), nullable=False, server_default="infra"))
        op.create_index("ix_events_kind", "events", ["kind"])
    op.alter_column("events", "zbx_eventid", type_=sa.String(96), existing_type=sa.String(32))
    op.alter_column("events", "hostid", type_=sa.String(64), existing_type=sa.String(32))
    op.alter_column("events", "triggerid", type_=sa.String(64), existing_type=sa.String(32))
    tables = insp.get_table_names()
    if "ext_tenants" not in tables:
        op.create_table(
            "ext_tenants",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.String(16), nullable=False), sa.Column("ext_id", sa.String(96), nullable=False),
            sa.Column("name", sa.String(255), nullable=False), sa.Column("kind", sa.String(32)),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL")),
            sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("source", "ext_id"))
        op.create_index("ix_ext_tenants_source", "ext_tenants", ["source"])
        op.create_index("ix_ext_tenants_client_id", "ext_tenants", ["client_id"])
    if "ext_assets" not in tables:
        op.create_table(
            "ext_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.String(16), nullable=False), sa.Column("ext_id", sa.String(96), nullable=False),
            sa.Column("name", sa.String(255), nullable=False), sa.Column("type", sa.String(32)),
            sa.Column("ext_tenant_id", sa.Integer(), sa.ForeignKey("ext_tenants.id", ondelete="SET NULL")),
            sa.Column("policy_name", sa.String(255)),
            sa.Column("last_success_at", sa.DateTime(timezone=True)), sa.Column("last_failure_at", sa.DateTime(timezone=True)),
            sa.Column("last_result", sa.String(64)), sa.Column("online", sa.Boolean()), sa.Column("offline_since", sa.DateTime(timezone=True)),
            sa.Column("ignored", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_seen_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("source", "ext_id"))
        op.create_index("ix_ext_assets_source", "ext_assets", ["source"])
        op.create_index("ix_ext_assets_ext_tenant_id", "ext_assets", ["ext_tenant_id"])


def downgrade():
    pass
