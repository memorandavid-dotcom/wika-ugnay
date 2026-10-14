from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from ugnay.db.models import (
    Department,
    IngestionRun,
    Language,
    Organization,
    Source,
    SourceObservation,
)

NOW = datetime.now(timezone.utc)


def assert_rejected(session, *objects):
    """Assert the database refuses these rows, without poisoning the session."""
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add_all(objects)
            session.flush()


def make_source(**overrides):
    data = dict(
        name="Test Source",
        url="https://example.gov.ph/directory",
        category="government_directory",
        connector_type="html_directory",
        collection_method="html_public_page",
    )
    data.update(overrides)
    return Source(**data)


def make_org(**overrides):
    data = dict(name="Test Agency", normalized_name="test agency", org_type="government_agency")
    data.update(overrides)
    return Organization(**data)


def make_observation(source_id, **overrides):
    data = dict(
        source_id=source_id,
        entity_type="organization",
        source_url="https://example.gov.ph/page1",
        raw_payload={"name": "Test Agency"},
        content_hash="a" * 64,
    )
    data.update(overrides)
    return SourceObservation(**data)


def test_core_tables_exist(session):
    found = set(inspect(session.connection()).get_table_names(schema="core"))
    expected = {
        "sources", "ingestion_runs", "source_observations", "languages",
        "organizations", "departments", "organization_languages",
    }
    assert expected <= found


def test_source_defaults_are_safe_at_database_level(session):
    session.execute(text(
        "INSERT INTO core.sources (name, url, category, connector_type, collection_method) "
        "VALUES ('Raw', 'https://example.gov.ph', 'government_directory', "
        "'html_directory', 'html_public_page')"
    ))
    row = session.execute(text(
        "SELECT enabled, review_status FROM core.sources WHERE name = 'Raw'"
    )).one()
    assert row.enabled is False
    assert row.review_status == "pending"


def test_source_cannot_be_enabled_without_approval(session):
    assert_rejected(
        session, make_source(enabled=True, review_status="pending", terms_reviewed_at=NOW)
    )


def test_source_cannot_be_enabled_without_terms_review(session):
    assert_rejected(
        session, make_source(enabled=True, review_status="approved", terms_reviewed_at=None)
    )


def test_source_can_be_enabled_after_review(session):
    source = make_source(enabled=True, review_status="approved", terms_reviewed_at=NOW)
    session.add(source)
    session.flush()
    assert source.enabled is True


def test_source_invalid_category_rejected(session):
    assert_rejected(session, make_source(category="dark_web"))


def test_organization_domain_must_be_unique(session):
    session.add(make_org(domain="example.edu.ph"))
    session.flush()
    assert_rejected(
        session, make_org(name="Other", normalized_name="other", domain="example.edu.ph")
    )


def test_organization_domain_must_be_lowercase(session):
    assert_rejected(session, make_org(domain="Example.EDU.ph"))


def test_organization_invalid_type_rejected(session):
    assert_rejected(session, make_org(org_type="spaceship"))


def test_organization_defaults_private_and_discovered(session):
    session.execute(text(
        "INSERT INTO core.organizations (name, normalized_name, org_type) "
        "VALUES ('Raw Org', 'raw org', 'ngo')"
    ))
    row = session.execute(text(
        "SELECT qualification_status, publication_status "
        "FROM core.organizations WHERE name = 'Raw Org'"
    )).one()
    assert tuple(row) == ("discovered", "private")


def test_department_name_unique_within_organization(session):
    org = make_org()
    session.add(org)
    session.flush()
    session.add(Department(organization_id=org.id, name="Linguistics"))
    session.flush()
    assert_rejected(session, Department(organization_id=org.id, name="Linguistics"))


def test_same_department_name_allowed_in_different_organizations(session):
    org_a = make_org()
    org_b = make_org(name="Another Agency", normalized_name="another agency")
    session.add_all([org_a, org_b])
    session.flush()
    session.add_all([
        Department(organization_id=org_a.id, name="Linguistics"),
        Department(organization_id=org_b.id, name="Linguistics"),
    ])
    session.flush()


@pytest.mark.parametrize("bad_code", ["TGL", "t1l", "tg"])
def test_language_code_format(session, bad_code):
    assert_rejected(session, Language(iso639_3=bad_code, name="Bad"))


def test_language_code_unique(session):
    session.add(Language(iso639_3="tgl", name="Tagalog"))
    session.flush()
    assert_rejected(session, Language(iso639_3="tgl", name="Duplicate"))


def test_ingestion_run_cannot_finish_before_start(session):
    source = make_source()
    session.add(source)
    session.flush()
    assert_rejected(
        session,
        IngestionRun(
            source_id=source.id,
            status="running",
            started_at=NOW,
            finished_at=NOW - timedelta(minutes=1),
        ),
    )


def test_duplicate_observation_rejected(session):
    source = make_source()
    session.add(source)
    session.flush()
    session.add(make_observation(source.id))
    session.flush()
    assert_rejected(session, make_observation(source.id))


def test_organization_language_link_unique(session):
    org = make_org()
    lang = Language(iso639_3="ceb", name="Cebuano")
    session.add_all([org, lang])
    session.flush()
    link = text(
        "INSERT INTO core.organization_languages (organization_id, language_id) "
        "VALUES (:o, :l)"
    )
    params = {"o": org.id, "l": lang.id}
    session.execute(link, params)
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.execute(link, params)