"""baseline NAVI — cria o schema inicial (somente CREATE; nunca DROP/TRUNCATE).

Revision ID: 0001
Revises:
"""
from alembic import op

import app.models  # noqa: F401
from app.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Downgrade do baseline desabilitado por segurança (restaure o backup).")
