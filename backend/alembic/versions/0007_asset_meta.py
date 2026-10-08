"""ext_assets.meta (dados especificos da origem: endpoints do EMS).

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    if "meta" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ext_assets")}:
        op.add_column("ext_assets", sa.Column("meta", sa.JSON(), nullable=True))


def downgrade():
    pass
