import itertools
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from ugnay.db.models import Language
from ugnay.db.models_resources import LanguageResource, ResourceRightsReview

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


def new_resource(**overrides):
    data = dict(
        title="Sample Dictionary",
        resource_type="dictionary",
        access_url=f"https://example.edu.ph/res/{uuid.uuid4()}",
    )
    data.update(overrides)
    return LanguageResource(**data)


def make_resource(session, **overrides):
    resource = new_resource(**overrides)
    session.add(resource)
    session.flush()
    return resource


def make_ready_resource(session):
    """Downloaded and extracted, but with no rights review yet."""
    return make_resource(
        session,
        download_status="downloaded",
        downloaded_at=NOW,
        file_sha256="a" * 64,
        local_path="raw/sample.pdf",
        extraction_status="extracted",
        extracted_at=NOW,
    )


_counter = itertools.count()


def new_review(resource, **overrides):
    data = dict(
        resource_id=resource.id,
        license="CC BY 4.0",
        permission_status="approved",
        permitted_uses=["internal_research", "product_use"],
        reviewer="cdo",
        reviewed_at=NOW,
        evidence_url=f"https://example.edu.ph/license/{next(_counter)}",
    )
    data.update(overrides)
    return ResourceRightsReview(**data)


def add_review(session, resource, **overrides):
    review = new_review(resource, **overrides)
    session.add(review)
    session.flush()
    return review


def try_approve(session, resource):
    resource.production_status = "approved_for_production"
    session.flush()


# ---------- resources ----------

def test_resource_tables_exist(session):
    found = set(inspect(session.connection()).get_table_names(schema="core"))
    assert {
        "language_resources", "resource_rights_reviews",
        "resource_languages", "resource_observations",
    } <= found


def test_resource_defaults_are_safe_at_database_level(session):
    row = session.execute(text(
        "INSERT INTO core.language_resources (title, resource_type, access_url) "
        "VALUES ('Raw', 'dictionary', 'https://example.edu.ph/raw') "
        "RETURNING download_status, extraction_status, production_status, publication_status"
    )).one()
    assert tuple(row) == ("not_downloaded", "not_extracted", "not_approved", "private")


def test_resource_invalid_type_rejected(session):
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(new_resource(resource_type="treasure_map"))
        session.flush()


def test_resource_access_url_must_be_unique(session):
    first = make_resource(session)
    with expect_db_error(session, UNIQUE_VIOLATION):
        session.add(new_resource(access_url=first.access_url))
        session.flush()


def test_downloaded_requires_hash_path_and_timestamp(session):
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(new_resource(download_status="downloaded", downloaded_at=NOW))
        session.flush()


def test_extracted_requires_downloaded(session):
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(new_resource(extraction_status="extracted", extracted_at=NOW))
        session.flush()


@pytest.mark.parametrize("bad_path", ["/etc/passwd", "C:/Windows/x.pdf", "raw/../../x.pdf"])
def test_local_path_must_stay_relative(session, bad_path):
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(new_resource(local_path=bad_path))
        session.flush()


def test_resource_language_link_unique(session):
    resource = make_resource(session)
    language = Language(iso639_3="qaa", name="Private-use test language")
    session.add(language)
    session.flush()
    link = text(
        "INSERT INTO core.resource_languages (resource_id, language_id) VALUES (:r, :l)"
    )
    params = {"r": resource.id, "l": language.id}
    session.execute(link, params)
    with expect_db_error(session, UNIQUE_VIOLATION):
        session.execute(link, params)


# ---------- reviews ----------

def test_approved_review_requires_evidence(session):
    resource = make_resource(session)
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(new_review(resource, evidence_url=None, evidence_note=None))
        session.flush()


def test_approved_review_requires_a_permitted_use(session):
    resource = make_resource(session)
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(new_review(resource, permitted_uses=[]))
        session.flush()


def test_unknown_status_cannot_grant_uses(session):
    resource = make_resource(session)
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(new_review(resource, permission_status="unknown",
                               permitted_uses=["internal_research"]))
        session.flush()


def test_invalid_permitted_use_rejected(session):
    resource = make_resource(session)
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(new_review(resource, permitted_uses=["time_travel"]))
        session.flush()


def test_resource_can_have_several_reviews(session):
    resource = make_resource(session)
    add_review(session, resource, permission_status="unknown", permitted_uses=[],
               evidence_url=None)
    add_review(session, resource)


def test_reviews_cannot_be_updated(session):
    review = add_review(session, make_resource(session))
    with expect_db_error(session, RAISED_BY_TRIGGER):
        session.execute(
            text("UPDATE core.resource_rights_reviews SET license = 'changed' WHERE id = :id"),
            {"id": review.id},
        )


def test_reviews_cannot_be_deleted(session):
    review = add_review(session, make_resource(session))
    with expect_db_error(session, RAISED_BY_TRIGGER):
        session.execute(
            text("DELETE FROM core.resource_rights_reviews WHERE id = :id"),
            {"id": review.id},
        )


# ---------- production approval ----------

def test_cannot_approve_without_any_review(session):
    resource = make_ready_resource(session)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        try_approve(session, resource)


def test_cannot_approve_when_latest_review_is_denied(session):
    resource = make_ready_resource(session)
    add_review(session, resource)  # older: approved
    add_review(session, resource, permission_status="denied", permitted_uses=[],
               evidence_url=None)  # newer: denied wins
    with expect_db_error(session, RAISED_BY_TRIGGER):
        try_approve(session, resource)


def test_cannot_approve_without_product_use(session):
    resource = make_ready_resource(session)
    add_review(session, resource, permitted_uses=["internal_research"])
    with expect_db_error(session, RAISED_BY_TRIGGER):
        try_approve(session, resource)


def test_cannot_approve_on_expired_review(session):
    resource = make_ready_resource(session)
    add_review(session, resource, reviewed_at=NOW - timedelta(days=30),
               expires_at=NOW - timedelta(days=1))
    with expect_db_error(session, RAISED_BY_TRIGGER):
        try_approve(session, resource)


def test_approval_succeeds_with_current_approved_review(session):
    resource = make_ready_resource(session)
    add_review(session, resource)
    try_approve(session, resource)
    session.refresh(resource)
    assert resource.production_status == "approved_for_production"


def test_approval_still_requires_extraction(session):
    resource = make_resource(session)  # not downloaded, not extracted
    add_review(session, resource)
    with expect_db_error(session, CHECK_VIOLATION):
        try_approve(session, resource)


def test_new_denied_review_revokes_production_approval(session):
    resource = make_ready_resource(session)
    add_review(session, resource)
    try_approve(session, resource)
    add_review(session, resource, permission_status="denied", permitted_uses=[],
               evidence_url=None)
    session.refresh(resource)
    assert resource.production_status == "revoked"


def test_reapproval_needs_a_new_approved_review(session):
    resource = make_ready_resource(session)
    add_review(session, resource)
    try_approve(session, resource)
    add_review(session, resource, permission_status="revoked", permitted_uses=[],
               evidence_url=None)
    session.refresh(resource)
    assert resource.production_status == "revoked"

    with expect_db_error(session, RAISED_BY_TRIGGER):
        try_approve(session, resource)

    add_review(session, resource)  # a fresh approval
    try_approve(session, resource)
    session.refresh(resource)
    assert resource.production_status == "approved_for_production"