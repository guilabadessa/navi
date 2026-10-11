"""Preferencias de push por usuario e controle de recuperacao.

Revision ID: 0022
Revises: 0021
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def _cols(t):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(t)}


def upgrade():
    u = _cols("users")
    if "push_min_sev" not in u:
        op.add_column("users", sa.Column("push_min_sev", sa.Integer, server_default="3", nullable=False))
    if "push_quiet_start" not in u:
        op.add_column("users", sa.Column("push_quiet_start", sa.Integer))
    if "push_quiet_end" not in u:
        op.add_column("users", sa.Column("push_quiet_end", sa.Integer))
    if "push_recovery" not in u:
        op.add_column("users", sa.Column("push_recovery", sa.Boolean, server_default="true", nullable=False))
    p = _cols("push_sent")
    if "delivered" not in p:
        op.add_column("push_sent", sa.Column("delivered", sa.Boolean, server_default="true", nullable=False))
    if "rec_sent" not in p:
        op.add_column("push_sent", sa.Column("rec_sent", sa.Boolean, server_default="false", nullable=False))


def downgrade():
    for c in ("rec_sent", "delivered"):
        op.drop_column("push_sent", c)
    for c in ("push_recovery", "push_quiet_end", "push_quiet_start", "push_min_sev"):
        op.drop_column("users", c)
