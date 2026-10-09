"""Aceite (ciencia) de falhas de rotina no painel.

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("job_status")}
    for name, typ in (("ack_sig", sa.String(255)), ("ack_by", sa.String(255)), ("ack_at", sa.DateTime(timezone=True))):
        if name not in cols:
            op.add_column("job_status", sa.Column(name, typ))


def downgrade():
    for name in ("ack_at", "ack_by", "ack_sig"):
        op.drop_column("job_status", name)
