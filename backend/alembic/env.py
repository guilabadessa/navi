from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.db import Base
import app.models  # noqa: F401

target_metadata = Base.metadata


def run_migrations_online():
    engine = create_engine(get_settings().db_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
