"""Remove a Evolution API: configuracoes, chave de provedor e estado de saude antigos.

Revision ID: 0032
Revises: 0031
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    c = op.get_bind()
    c.execute(sa.text("delete from settings where key like 'evolution.%' or key = 'whatsapp.provider'"))
    c.execute(sa.text("delete from health_checks where name = 'evolution'"))


def downgrade():
    pass  # configuracao descartada de proposito; nao ha o que restaurar
