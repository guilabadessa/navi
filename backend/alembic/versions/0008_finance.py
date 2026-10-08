"""Conta Azul: vinculo do cliente, espelho financeiro e permissoes extras do usuario.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _cols(t):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(t)}


def upgrade():
    if "extra_perms" not in _cols("users"):
        op.add_column("users", sa.Column("extra_perms", sa.JSON(), nullable=True))
    c = _cols("clients")
    if "ca_person_id" not in c:
        op.add_column("clients", sa.Column("ca_person_id", sa.String(64), nullable=True))
        op.create_index("ix_clients_ca_person_id", "clients", ["ca_person_id"])
    if "ca_match" not in c:
        op.add_column("clients", sa.Column("ca_match", sa.String(16), nullable=True))
    if "fin_docs" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "fin_docs",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("kind", sa.String(16), nullable=False, index=True),
            sa.Column("ext_id", sa.String(96), nullable=False),
            sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id", ondelete="CASCADE"), index=True),
            sa.Column("person_id", sa.String(64), index=True),
            sa.Column("number", sa.String(64)),
            sa.Column("description", sa.String(512)),
            sa.Column("status", sa.String(32)),
            sa.Column("amount", sa.Float),
            sa.Column("paid", sa.Float),
            sa.Column("due_date", sa.Date),
            sa.Column("issue_date", sa.Date),
            sa.Column("links", sa.JSON),
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("kind", "ext_id"),
        )


def downgrade():
    pass
