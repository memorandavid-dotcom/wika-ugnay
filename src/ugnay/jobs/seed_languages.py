"""Load Philippine languages into core.languages from a Glottolog CLDF languages.csv.

Dry run (default, writes nothing):
    python -m ugnay.jobs.seed_languages --file data/raw/glottolog_languages.csv --source-version "5.3 (downloaded 2026-10-16)"
Write to the database:
    add --apply
"""
import argparse
import csv
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ugnay.config import get_settings
from ugnay.db.models import Language
from ugnay.db.session import get_session
from ugnay.logging_config import configure_logging

REQUIRED_COLUMNS = {"ID", "Name", "Level", "ISO639P3code", "Countries", "Family_ID"}
ISO_PATTERN = re.compile(r"^[a-z]{3}$")


@dataclass(frozen=True)
class LanguageRow:
    iso639_3: str
    name: str
    family: str | None
    glottocode: str


@dataclass
class LoadStats:
    scanned: int = 0
    matched_country: int = 0
    skipped_no_iso: int = 0
    skipped_bad_iso: int = 0
    skipped_duplicate: int = 0
    rows: int = 0


def load_languages(
    csv_path: Path, country: str = "PH"
) -> tuple[list[LanguageRow], LoadStats]:
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing expected columns: {sorted(missing)}")
        records = list(reader)

    names = {rec["ID"]: rec["Name"] for rec in records}
    stats = LoadStats(scanned=len(records))
    seen: set[str] = set()
    rows: list[LanguageRow] = []

    for rec in records:
        if rec["Level"] != "language":
            continue
        countries = {c.strip().upper() for c in rec["Countries"].split(";") if c.strip()}
        if country.upper() not in countries:
            continue
        stats.matched_country += 1

        iso = rec["ISO639P3code"].strip()
        if not iso:
            stats.skipped_no_iso += 1
            continue
        if not ISO_PATTERN.match(iso):
            stats.skipped_bad_iso += 1
            continue
        if iso in seen:
            stats.skipped_duplicate += 1
            continue
        seen.add(iso)

        family_id = rec["Family_ID"].strip()
        family = names.get(family_id) if family_id and family_id != rec["ID"] else None
        rows.append(LanguageRow(iso, rec["Name"].strip(), family, rec["ID"]))

    stats.rows = len(rows)
    return rows, stats


def upsert_languages(
    session: Session, rows: list[LanguageRow], source_version: str
) -> tuple[int, int]:
    """Idempotent. Returns (inserted, updated). The caller owns the transaction."""
    if not rows:
        return 0, 0
    values = [
        dict(
            id=uuid.uuid4(),
            iso639_3=row.iso639_3,
            name=row.name,
            family=row.family,
            notes=f"Source: Glottolog {source_version}; glottocode {row.glottocode}",
        )
        for row in rows
    ]
    stmt = pg_insert(Language).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Language.iso639_3],
        set_={
            "name": stmt.excluded.name,
            "family": stmt.excluded.family,
            "notes": stmt.excluded.notes,
            "updated_at": func.now(),
        },
    ).returning(literal_column("(xmax = 0)").label("inserted"))
    flags = [row.inserted for row in session.execute(stmt)]
    inserted = sum(1 for flag in flags if flag)
    return inserted, len(flags) - inserted


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Seed core.languages from Glottolog CLDF.")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--source-version", required=True,
                        help='e.g. "5.3 (glottolog-cldf master, downloaded 2026-10-16)"')
    parser.add_argument("--country", default="PH")
    parser.add_argument("--apply", action="store_true", help="write to the database")
    args = parser.parse_args(argv)

    configure_logging(get_settings().log_level)
    rows, stats = load_languages(args.file, args.country)

    print(f"rows scanned:               {stats.scanned}")
    print(f"language-level in {args.country}:       {stats.matched_country}")
    print(f"skipped (no ISO 639-3 code): {stats.skipped_no_iso}")
    print(f"skipped (malformed code):    {stats.skipped_bad_iso}")
    print(f"skipped (duplicate code):    {stats.skipped_duplicate}")
    print(f"ready to load:               {stats.rows}")
    for row in rows[:10]:
        print(f"  {row.iso639_3}  {row.name}  [{row.family}]")
    if stats.rows > 10:
        print(f"  ... and {stats.rows - 10} more")

    if not rows:
        print("Nothing to load. Check the file and the --country value.")
        return 1
    if not args.apply:
        print("DRY RUN: nothing written. Re-run with --apply to write.")
        return 0

    with get_session() as session:
        inserted, updated = upsert_languages(session, rows, args.source_version)
        session.commit()
    print(f"APPLIED: {inserted} inserted, {updated} updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())