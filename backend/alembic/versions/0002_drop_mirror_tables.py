"""NAVI passa a consultar itens/triggers ao vivo na API: remove tabelas-espelho (somente do banco NAVI).

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TABLE IF EXISTS zbx_items")
    op.execute("DROP TABLE IF EXISTS zbx_triggers")


def downgrade():
    pass  # tabelas eram apenas cache; sao repovoaveis pela API
