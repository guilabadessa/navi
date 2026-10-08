"""Alertas por e-mail: canais nas regras, padrao de e-mail no cliente e canal nos despachos.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("alert_rules", sa.Column("notify_whatsapp", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("alert_rules", sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("alert_rules", sa.Column("email_to", sa.Text(), nullable=True))
    op.add_column("clients", sa.Column("mail_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("clients", sa.Column("alert_emails", sa.Text(), nullable=True))
    op.add_column("dispatches", sa.Column("channel", sa.String(16), nullable=False, server_default="whatsapp"))
    op.alter_column("dispatches", "dest_jid", type_=sa.String(512), existing_type=sa.String(128))


def downgrade():
    pass  # somente colunas adicionais; manter dados
