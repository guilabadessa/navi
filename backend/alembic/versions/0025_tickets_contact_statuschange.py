"""Chamados: telefone de contato e marcacao de mudanca de situacao na mensagem.

Revision ID: 0025
Revises: 0024
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tickets", sa.Column("contact_phone", sa.String(32)))
    op.add_column("ticket_messages", sa.Column("status_change", sa.String(24)))


def downgrade():
    op.drop_column("ticket_messages", "status_change")
    op.drop_column("tickets", "contact_phone")
