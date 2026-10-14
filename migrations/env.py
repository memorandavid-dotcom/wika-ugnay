from alembic import context
from sqlalchemy import create_engine, pool

from ugnay.config import get_settings
from ugnay.db.base import Base
import ugnay.db.models  # noqa: F401  (importing registers the tables)

config = context.config
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == "core"
    return True


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported in this project.")
run_migrations_online()