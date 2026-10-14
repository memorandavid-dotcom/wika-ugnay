import sys

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ugnay.config import get_settings
from ugnay.db.session import get_engine
from ugnay.logging_config import configure_logging


def check_database() -> tuple[bool, str]:
    try:
        with get_engine().connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar_one()
        return True, version
    except SQLAlchemyError as exc:
        first_line = str(exc).strip().splitlines()[0]
        return False, f"{type(exc).__name__}: {first_line}"


def main() -> int:
    configure_logging(get_settings().log_level)
    ok, detail = check_database()
    print(("OK: " if ok else "FAIL: ") + detail)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())