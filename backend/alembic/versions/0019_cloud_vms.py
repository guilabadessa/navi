"""Cloud Orca: maquinas sincronizadas (monitoramento, alertas e relatorios) e falhas de acesso por conta.

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if "fails" not in {c["name"] for c in insp.get_columns("cloud_accounts")}:
        op.add_column("cloud_accounts", sa.Column("fails", sa.Integer, nullable=False, server_default="0"))
    if "cloud_vms" not in insp.get_table_names():
        op.create_table("cloud_vms",
                        sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("uuid", sa.String(64), nullable=False, unique=True),
                        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True),
                        sa.Column("name", sa.String(255)),
                        sa.Column("state", sa.String(24)),
                        sa.Column("zone", sa.String(64)),
                        sa.Column("cpu", sa.Integer),
                        sa.Column("ram_mb", sa.Integer),
                        sa.Column("disk_gb", sa.Integer),
                        sa.Column("ip", sa.String(64)),
                        sa.Column("os", sa.String(255)),
                        sa.Column("network", sa.String(128)),
                        sa.Column("state_since", sa.DateTime(timezone=True)),
                        sa.Column("last_seen", sa.DateTime(timezone=True)),
                        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
                        sa.Column("expected_off", sa.Boolean, nullable=False, server_default=sa.false()),
                        sa.Column("grace_until", sa.DateTime(timezone=True)),
                        sa.Column("ignored", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_table("cloud_vms")
    op.drop_column("cloud_accounts", "fails")
