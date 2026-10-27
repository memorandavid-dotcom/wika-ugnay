"""Manage the source registry.

  python -m ugnay.jobs.manage_sources sync [--file config/sources.yaml] [--apply]
  python -m ugnay.jobs.manage_sources list
  python -m ugnay.jobs.manage_sources review NAME --decision approved --reviewer WHO --terms-url URL --notes "..." [--robots-checked]
  python -m ugnay.jobs.manage_sources enable NAME
  python -m ugnay.jobs.manage_sources disable NAME
  python -m ugnay.jobs.manage_sources fail-stale
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from ugnay.config import get_settings
from ugnay.db.models import Source
from ugnay.db.session import get_session
from ugnay.logging_config import configure_logging
from ugnay.sources.registry import (
    SourceNotApproved,
    fail_stale_runs,
    load_source_configs,
    review_source,
    set_enabled,
    sync_sources,
)


def find_source(session, name: str) -> Source:
    source = session.execute(select(Source).where(Source.name == name)).scalar_one_or_none()
    if source is None:
        raise ValueError(f"no source named {name!r}")
    return source


def cmd_sync(args) -> int:
    configs = load_source_configs(args.file)
    with get_session() as session:
        result = sync_sources(session, configs)
        print(f"created {result.created}, updated {result.updated}, unchanged {result.unchanged}")
        for name in result.reviews_reset:
            print(f"REVIEW RESET (needs a new review): {name}")
        if args.apply:
            session.commit()
            print("APPLIED.")
        else:
            session.rollback()
            print("DRY RUN: nothing written. Re-run with --apply.")
    return 0


def cmd_list(args) -> int:
    with get_session() as session:
        sources = session.execute(select(Source).order_by(Source.name)).scalars().all()
        if not sources:
            print("No sources registered. Run: sync --apply")
        for s in sources:
            reviewed = s.terms_reviewed_at.date().isoformat() if s.terms_reviewed_at else "-"
            success = s.last_success_at.date().isoformat() if s.last_success_at else "-"
            error = (s.last_error or "")[:60]
            print(
                f"{s.name} | {s.review_status} | enabled={s.enabled} | "
                f"reviewed {reviewed} | last success {success} | {error}"
            )
    return 0


def cmd_review(args) -> int:
    with get_session() as session:
        source = find_source(session, args.name)
        review_source(
            session, source, decision=args.decision, reviewer=args.reviewer,
            notes=args.notes, terms_url=args.terms_url, robots_checked=args.robots_checked,
        )
        session.commit()
    print("Review recorded. The source is still disabled; run 'enable' to turn it on.")
    return 0


def cmd_enable(args, enabled: bool) -> int:
    with get_session() as session:
        set_enabled(session, find_source(session, args.name), enabled)
        session.commit()
    print(("Enabled." if enabled else "Disabled."))
    return 0


def cmd_fail_stale(args) -> int:
    with get_session() as session:
        count = fail_stale_runs(session)
        session.commit()
    print(f"Marked {count} stuck run(s) as failed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Manage the source registry.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync")
    p_sync.add_argument("--file", type=Path, default=Path("config/sources.yaml"))
    p_sync.add_argument("--apply", action="store_true")
    sub.add_parser("list")
    p_review = sub.add_parser("review")
    p_review.add_argument("name")
    p_review.add_argument("--decision", required=True, choices=["approved", "rejected"])
    p_review.add_argument("--reviewer", required=True)
    p_review.add_argument("--terms-url")
    p_review.add_argument("--notes", required=True)
    p_review.add_argument("--robots-checked", action="store_true")
    for name in ("enable", "disable"):
        sub.add_parser(name).add_argument("name")
    sub.add_parser("fail-stale")

    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    try:
        if args.command == "sync":
            return cmd_sync(args)
        if args.command == "list":
            return cmd_list(args)
        if args.command == "review":
            return cmd_review(args)
        if args.command == "enable":
            return cmd_enable(args, True)
        if args.command == "disable":
            return cmd_enable(args, False)
        return cmd_fail_stale(args)
    except (ValueError, SourceNotApproved) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())