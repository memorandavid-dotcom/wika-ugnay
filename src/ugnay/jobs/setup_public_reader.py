"""Give ugnay_public_reader a login password (from .env) and verify its limits."""
import sys

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from ugnay.config import PUBLIC_READER_ROLE, get_settings
from ugnay.logging_config import configure_logging


def set_password() -> None:
    settings = get_settings()
    if settings.public_reader_password is None:
        raise SystemExit("Set PUBLIC_READER_PASSWORD in .env first.")
    password = settings.public_reader_password.get_secret_value()
    if len(password) < 16:
        raise SystemExit("PUBLIC_READER_PASSWORD must be at least 16 characters.")
    if password == settings.postgres_password.get_secret_value():
        raise SystemExit("PUBLIC_READER_PASSWORD must differ from POSTGRES_PASSWORD.")
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
    ) as conn:
        conn.execute(
            sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                sql.Identifier(PUBLIC_READER_ROLE), sql.Literal(password)
            )
        )


def verify() -> bool:
    engine = create_engine(get_settings().public_database_url, pool_pre_ping=True)
    ok = True
    try:
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM public_view.organizations")).scalar_one()
            print(f"OK: public_view.organizations readable ({count} rows)")
        with engine.connect() as conn:
            try:
                conn.execute(text("SELECT count(*) FROM core.organizations"))
                print("PROBLEM: core.organizations is readable by the public role")
                ok = False
            except ProgrammingError:
                print("OK: core.organizations is denied to the public role")
    finally:
        engine.dispose()
    return ok


def main() -> int:
    configure_logging(get_settings().log_level)
    set_password()
    print(f"Password set for role {PUBLIC_READER_ROLE}.")
    return 0 if verify() else 1


if __name__ == "__main__":
    sys.exit(main())