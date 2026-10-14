from alembic import context
from sqlalchemy import create_engine, pool

from ugnay.config import get_settings

config = context.config
target_metadata = None  # Phase 2: set to Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported in this project.")
run_migrations_online()