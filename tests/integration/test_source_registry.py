import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from ugnay.db.models import Source
from ugnay.db.models_sources import SourceReview
from ugnay.sources.registry import (
    SourceBusy,
    SourceConfig,
    SourceNotApproved,
    assert_url_allowed,
    fail_stale_runs,
    finish_run,
    require_ingestable,
    review_source,
    set_enabled,
    start_run,
    sync_sources,
)

NOW = datetime.now(timezone.utc)
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
RAISED_BY_TRIGGER = "P0001"


@contextmanager
def expect_db_error(session, sqlstate):
    with pytest.raises(DBAPIError) as info:
        with session.begin_nested():
            yield
    actual = info.value.orig.sqlstate
    assert actual == sqlstate, f"expected {sqlstate}, got {actual}: {info.value.orig}"


def config(**overrides):
    data = dict(
        name=f"Source {uuid.uuid4().hex[:8]}",
        url="https://www.example.gov.ph/agencies",
        category="government_directory",
        connector_type="html_directory",
        collection_method="html_public_page",
        allowed_domains=["example.gov.ph"],
    )
    data.update(overrides)
    return SourceConfig(**data)


def make_source(session, **overrides):
    cfg = config(**overrides)
    sync_sources(session, [cfg])
    return session.execute(select(Source).where(Source.name == cfg.name)).scalar_one()


def approve(session, source, **overrides):
    data = dict(
        decision="approved", reviewer="cdo", notes="Terms allow public directory use",
        terms_url="https://www.example.gov.ph/terms", robots_checked=True,
    )
    data.update(overrides)
    return review_source(session, source, **data)


def make_live_source(session, **overrides):
    source = make_source(session, **overrides)
    approve(session, source)
    set_enabled(session, source, True)
    return source


# ---------- sync ----------

def test_sync_creates_pending_disabled_sources(session):
    source = make_source(session)
    assert (source.review_status, source.enabled) == ("pending", False)


def test_sync_is_idempotent(session):
    cfg = config()
    first = sync_sources(session, [cfg])
    second = sync_sources(session, [cfg])
    assert (first.created, second.created, second.unchanged) == (1, 0, 1)


def test_sync_operational_change_keeps_approval(session):
    source = make_live_source(session)
    result = sync_sources(session, [config(name=source.name, requests_per_minute=5)])
    session.refresh(source)
    assert result.updated == 1 and result.reviews_reset == []
    assert source.enabled and source.review_status == "approved"
    assert source.requests_per_minute == 5


def test_sync_material_change_resets_review(session):
    source = make_live_source(session)
    result = sync_sources(
        session,
        [config(name=source.name, allowed_domains=["example.gov.ph", "extra.gov.ph"])],
    )
    assert result.reviews_reset == [source.name]
    assert source.review_status == "pending" and source.enabled is False
    assert source.terms_reviewed_at is None


# ---------- review workflow ----------

def test_approval_writes_audit_row_and_does_not_enable(session):
    source = make_source(session)
    approve(session, source)
    rows = session.scalars(select(SourceReview).where(SourceReview.source_id == source.id)).all()
    assert len(rows) == 1 and rows[0].decision == "approved"
    assert source.review_status == "approved" and source.enabled is False


def test_approval_needs_terms_url_and_notes(session):
    source = make_source(session)
    with pytest.raises(ValueError):
        approve(session, source, terms_url=None)
    with pytest.raises(ValueError):
        approve(session, source, notes="   ")


def test_web_approval_needs_robots_confirmation(session):
    source = make_source(session)
    with pytest.raises(ValueError):
        approve(session, source, robots_checked=False)


def test_api_source_does_not_need_robots(session):
    source = make_source(session, collection_method="api", connector_type="api_client")
    approve(session, source, robots_checked=False)
    assert source.review_status == "approved"


def test_database_requires_robots_for_web_approval(session):
    source = make_source(session)
    with expect_db_error(session, CHECK_VIOLATION):
        session.execute(
            text("UPDATE core.sources SET review_status = 'approved', terms_reviewed_at = now(), "
                 "reviewed_by = 'cdo', terms_url = 'https://x.ph/terms', review_notes = 'ok' "
                 "WHERE id = :id"),
            {"id": source.id},
        )


def test_database_requires_evidence_for_approval(session):
    source = make_source(session)
    with expect_db_error(session, CHECK_VIOLATION):
        session.execute(
            text("UPDATE core.sources SET review_status = 'approved', robots_checked_at = now() "
                 "WHERE id = :id"),
            {"id": source.id},
        )


def test_rejected_source_cannot_be_enabled(session):
    source = make_source(session)
    approve(session, source, decision="rejected", terms_url=None, robots_checked=False,
            notes="Terms forbid automated collection")
    with pytest.raises(SourceNotApproved):
        set_enabled(session, source, True)


def test_unreviewed_source_cannot_be_enabled(session):
    with pytest.raises(SourceNotApproved):
        set_enabled(session, make_source(session), True)


def test_stale_review_blocks_enabling(session):
    source = make_source(session)
    approve(session, source, reviewed_at=NOW - timedelta(days=400))
    with pytest.raises(SourceNotApproved):
        set_enabled(session, source, True)


def test_disabled_source_is_not_ingestable(session):
    source = make_source(session)
    approve(session, source)
    with pytest.raises(SourceNotApproved):
        require_ingestable(source)


def test_url_must_stay_inside_allowed_domains(session):
    source = make_live_source(session)
    assert_url_allowed(source, "https://www.example.gov.ph/page")
    for bad in ("https://evil.example.com/x", "ftp://www.example.gov.ph/x",
                "https://example.gov.ph.evil.com/"):
        with pytest.raises(SourceNotApproved):
            assert_url_allowed(source, bad)


# ---------- ingestion runs ----------

def test_start_run_refused_for_pending_source(session):
    with pytest.raises(SourceNotApproved):
        start_run(session, make_source(session))


def test_database_blocks_run_for_unapproved_source(session):
    source = make_source(session)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        session.execute(text("INSERT INTO core.ingestion_runs (source_id) VALUES (:s)"),
                        {"s": source.id})


def test_start_run_creates_running_run(session):
    run = start_run(session, make_live_source(session))
    assert run.status == "running"


def test_second_run_refused_while_one_is_running(session):
    source = make_live_source(session)
    start_run(session, source)
    with pytest.raises(SourceBusy):
        start_run(session, source)


def test_database_allows_only_one_running_run(session):
    source = make_live_source(session)
    start_run(session, source)
    with expect_db_error(session, UNIQUE_VIOLATION):
        session.execute(text("INSERT INTO core.ingestion_runs (source_id) VALUES (:s)"),
                        {"s": source.id})


def test_finish_run_success_updates_source(session):
    source = make_live_source(session)
    run = start_run(session, source)
    finish_run(session, run, status="succeeded", fetched=10, new=8, updated=2)
    session.refresh(source)
    session.refresh(run)
    assert run.status == "succeeded" and run.finished_at is not None
    assert (run.records_fetched, run.records_new, run.records_updated) == (10, 8, 2)
    assert source.last_success_at is not None and source.last_error is None


def test_finish_run_failure_keeps_last_success(session):
    source = make_live_source(session)
    finish_run(session, start_run(session, source), status="succeeded")
    session.refresh(source)
    first_success = source.last_success_at

    failed = start_run(session, source)  # works because the first run finished
    finish_run(session, failed, status="failed", error="x" * 2000)
    session.refresh(source)
    assert source.last_success_at == first_success
    assert len(source.last_error) == 500


def test_finish_run_twice_refused(session):
    run = start_run(session, make_live_source(session))
    finish_run(session, run, status="succeeded")
    with pytest.raises(ValueError):
        finish_run(session, run, status="succeeded")


def test_fail_stale_runs(session):
    run = start_run(session, make_live_source(session))
    run.started_at = NOW - timedelta(hours=7)
    session.flush()
    assert fail_stale_runs(session) >= 1
    session.refresh(run)
    assert run.status == "failed"


# ---------- audit log ----------

@pytest.mark.parametrize("statement", [
    "UPDATE core.source_reviews SET notes = 'changed' WHERE source_id = :s",
    "DELETE FROM core.source_reviews WHERE source_id = :s",
])
def test_review_log_is_append_only(session, statement):
    source = make_source(session)
    approve(session, source)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        session.execute(text(statement), {"s": source.id})