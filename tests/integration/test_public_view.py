import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ugnay.db.models_people import Contact, ContactAffiliation, ContactMethod
from ugnay.db.models_resources import LanguageResource
from ugnay.publishing.export import PUBLIC_VIEWS, export_public_views
from ugnay.publishing.leak_scan import scan_directory

NOW = datetime.now(timezone.utc)
INSUFFICIENT_PRIVILEGE = "42501"

EXPECTED_COLUMNS = {
    "organizations": {"id", "name", "org_type", "region", "website_url", "domain",
                      "date_last_updated"},
    "organization_languages": {"organization_id", "iso639_3", "language_name"},
    "language_resources": {"id", "title", "resource_type", "description", "publisher_name",
                           "custodian_name", "access_url", "publication_year",
                           "date_last_updated", "license"},
    "resource_languages": {"resource_id", "iso639_3", "language_name"},
    "languages": {"iso639_3", "name", "family"},
    "organization_contact_summary": {"organization_id", "professional_contacts_band",
                                     "has_reviewed_official_inbox"},
}


@contextmanager
def expect_db_error(session, sqlstate):
    with pytest.raises(DBAPIError) as info:
        with session.begin_nested():
            yield
    actual = info.value.orig.sqlstate
    assert actual == sqlstate, f"expected {sqlstate}, got {actual}: {info.value.orig}"


def become_public(session):
    session.execute(text("SET LOCAL ROLE ugnay_public_reader"))


def become_admin(session):
    session.execute(text("RESET ROLE"))


def public_scalar(session, sql, params=None):
    become_public(session)
    try:
        return session.execute(text(sql), params or {}).scalar_one()
    finally:
        become_admin(session)


def publish(session, org):
    org.publication_status = "publishable"
    session.flush()


def add_contact(session, org, obs, name, reviewed=True):
    if reviewed:
        contact = Contact(full_name=name, review_status="reviewed",
                          collection_purpose="Language-resource inquiry",
                          source_observation_id=obs.id, reviewed_by="cdo", reviewed_at=NOW)
    else:
        contact = Contact(full_name=name)
    session.add(contact)
    session.flush()
    session.add(ContactAffiliation(contact_id=contact.id, organization_id=org.id,
                                   source_observation_id=obs.id))
    session.flush()
    return contact


BAND_SQL = ("SELECT professional_contacts_band FROM public_view.organization_contact_summary "
            "WHERE organization_id = :id")


# ---------- the public contract ----------

def test_public_views_are_exactly_the_approved_set(session):
    found = set(session.execute(text(
        "SELECT table_name FROM information_schema.views WHERE table_schema = 'public_view'"
    )).scalars().all())
    assert found == set(PUBLIC_VIEWS) == set(EXPECTED_COLUMNS)


@pytest.mark.parametrize("view", sorted(EXPECTED_COLUMNS))
def test_view_columns_are_pinned(session, view):
    columns = set(session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public_view' AND table_name = :v"), {"v": view}
    ).scalars().all())
    assert columns == EXPECTED_COLUMNS[view]


def test_public_role_is_unprivileged(session):
    row = session.execute(text(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolconnlimit "
        "FROM pg_roles WHERE rolname = 'ugnay_public_reader'")).one()
    assert tuple(row) == (False, False, False, False, 5)


@pytest.mark.parametrize("table", [
    "organizations", "contacts", "contact_methods", "suppression_list",
    "outreach_activities", "resource_rights_reviews", "source_observations",
])
def test_public_role_cannot_read_core_tables(session, table):
    with expect_db_error(session, INSUFFICIENT_PRIVILEGE):
        become_public(session)
        session.execute(text(f"SELECT count(*) FROM core.{table}"))


@pytest.mark.parametrize("statement", [
    "DELETE FROM public_view.organizations",
    "UPDATE public_view.organizations SET name = 'x'",
])
def test_public_role_cannot_write_views(session, statement):
    with expect_db_error(session, INSUFFICIENT_PRIVILEGE):
        become_public(session)
        session.execute(text(statement))


# ---------- what the views show ----------

def test_private_organizations_are_hidden_until_publishable(session, org):
    query = "SELECT count(*) FROM public_view.organizations WHERE id = :id"
    assert public_scalar(session, query, {"id": org.id}) == 0
    publish(session, org)
    assert public_scalar(session, query, {"id": org.id}) == 1


def test_contact_band_is_none_without_contacts(session, org):
    publish(session, org)
    assert public_scalar(session, BAND_SQL, {"id": org.id}) == "none"


def test_contact_band_ignores_unreviewed_contacts(session, org, new_observation):
    publish(session, org)
    obs = new_observation("contact")
    add_contact(session, org, obs, "Reviewed Person")
    add_contact(session, org, obs, "Unreviewed Person", reviewed=False)
    assert public_scalar(session, BAND_SQL, {"id": org.id}) == "1-2"


def test_contact_band_for_three_reviewed_contacts(session, org, new_observation):
    publish(session, org)
    obs = new_observation("contact")
    for name in ("Person One", "Person Two", "Person Three"):
        add_contact(session, org, obs, name)
    assert public_scalar(session, BAND_SQL, {"id": org.id}) == "3-5"


# ---------- end-to-end leak test ----------

def test_public_export_contains_no_personal_data(session, org, new_observation, tmp_path):
    obs = new_observation("contact")
    org.domain = "example.edu.ph"
    org.website_url = "https://example.edu.ph"
    publish(session, org)

    contact = add_contact(session, org, obs, "Juan Dela Cruz")
    session.add(ContactMethod(
        method_type="email", value="juan.delacruz@example.edu.ph",
        normalized_value="juan.delacruz@example.edu.ph", collection_tier=3,
        is_official_inbox=False, contact_id=contact.id, source_observation_id=obs.id))
    session.add(ContactMethod(
        method_type="email", value="registrar@example.edu.ph",
        normalized_value="registrar@example.edu.ph", collection_tier=1,
        is_official_inbox=True, organization_id=org.id, source_observation_id=obs.id))
    session.add(LanguageResource(
        title="Sample Dictionary", resource_type="dictionary",
        access_url=f"https://example.edu.ph/{uuid.uuid4()}", custodian_org_id=org.id,
        publication_status="publishable"))
    session.flush()

    names = session.execute(text(
        "SELECT full_name FROM core.contacts WHERE review_status <> 'erased'")).scalars().all()
    assert "Juan Dela Cruz" in names

    become_public(session)
    counts = export_public_views(session, tmp_path)
    become_admin(session)

    assert counts["organizations"] >= 1 and counts["language_resources"] >= 1
    assert scan_directory(tmp_path, names) == []
    combined = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*.csv"))
    assert "Fixture Org" in combined  # the export is not vacuously empty