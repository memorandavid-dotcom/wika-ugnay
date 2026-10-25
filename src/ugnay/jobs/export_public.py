"""Export public views to data/exports/public and leak-scan the result."""
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from ugnay.config import get_settings
from ugnay.db.session import get_session
from ugnay.logging_config import configure_logging
from ugnay.publishing.export import export_public_views
from ugnay.publishing.leak_scan import scan_directory

OUT_DIR = Path("data/exports/public")


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = create_engine(settings.public_database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            counts = export_public_views(conn, OUT_DIR)
    finally:
        engine.dispose()
    for view, rows in counts.items():
        print(f"{view}: {rows} rows")

    with get_session() as session:
        names = session.execute(
            text("SELECT full_name FROM core.contacts WHERE review_status <> 'erased'")
        ).scalars().all()
    findings = scan_directory(OUT_DIR, names)
    if findings:
        for item in findings:
            print(f"LEAK: {item}")
        print(f"LEAK SCAN FAILED: do not share anything in {OUT_DIR}.")
        return 1
    print("Leak scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())