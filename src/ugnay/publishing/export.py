"""Export the public views to CSV. Call with a connection that is running as the public role."""
import csv
from pathlib import Path

from sqlalchemy import text

# Fixed list, never user input. A test checks it matches the views in the database.
PUBLIC_VIEWS = (
    "organizations",
    "organization_languages",
    "language_resources",
    "resource_languages",
    "languages",
    "organization_contact_summary",
)


def export_public_views(conn, out_dir: Path) -> dict[str, int]:
    """`conn` can be a SQLAlchemy Connection or Session. Returns rows written per view."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for view in PUBLIC_VIEWS:
        result = conn.execute(text(f"SELECT * FROM public_view.{view} ORDER BY 1"))
        columns = list(result.keys())
        rows = result.fetchall()
        with (out_dir / f"{view}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for row in rows:
                writer.writerow("" if value is None else value for value in row)
        counts[view] = len(rows)
    return counts