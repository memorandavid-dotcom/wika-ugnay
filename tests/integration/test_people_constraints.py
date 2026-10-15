from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from ugnay.db.models import Department, Organization
from ugnay.db.models_people import (
    Contact,
    ContactAffiliation,
    ContactMethod,
    SuppressionEntry,
)
from ugnay.db.repository import erase_contact
from ugnay.outreach.suppression import add_suppression, is_suppressed, lift_suppression

NOW = datetime.now(timezone.utc)


REJECTION_CODES = {"23502", "23503", "23505", "23514", "P0001"}
# not-null, foreign key, unique, check, and trigger RAISE EXCEPTION


def _check_rejected(exc):
    code = getattr(exc.orig, "sqlstate", None)
    assert code in REJECTION_CODES, f"unexpected database error {code}: {exc.orig}"


def assert_rejected(session, *objects):
    with pytest.raises(DBAPIError) as info:
        with session.begin_nested():
            session.add_all(objects)
            session.flush()
    _check_rejected(info.value)


def assert_sql_rejected(session, sql, params=None):
    with pytest.raises(DBAPIError) as info:
        with session.begin_nested():
            session.execute(text(sql), params or {})
    _check_rejected(info.value)


def make_contact(session, **overrides):
    data = dict(full_name="Juan Dela Cruz")
    data.update(overrides)
    contact = Contact(**data)
    session.add(contact)
    session.flush()
    return contact


def make_org_method(org, obs, **overrides):
    data = dict(
        method_type="email",
        value="Registrar@Example.edu.ph",
        normalized_value="registrar@example.edu.ph",
        collection_tier=1,
        is_official_inbox=True,
        organization_id=org.id,
        source_observation_id=obs.id,
    )
    data.update(overrides)
    return ContactMethod(**data)


def make_person_method(contact, obs, **overrides):
    data = dict(
        method_type="email",
        value="juan@example.edu.ph",
        normalized_value="juan@example.edu.ph",
        collection_tier=3,
        is_official_inbox=False,
        contact_id=contact.id,
        source_observation_id=obs.id,
    )
    data.update(overrides)
    return ContactMethod(**data)


def make_suppression(**overrides):
    data = dict(
        value_type="email",
        normalized_value="optout@example.edu.ph",
        reason="opt_out",
        request_received_at=NOW,
        request_channel="email",
        added_by="cdo",
    )
    data.update(overrides)
    return SuppressionEntry(**data)


def suppress(session, value_type, value):
    return add_suppression(
        session,
        value_type=value_type,
        value=value,
        reason="opt_out",
        request_received_at=NOW,
        added_by="cdo",
        request_channel="email",
    )


# ---------- contacts ----------

def test_reviewed_contact_requires_purpose(session, new_observation):
    obs = new_observation()
    assert_rejected(
        session,
        Contact(full_name="A B", review_status="reviewed", source_observation_id=obs.id,
                reviewed_by="cdo", reviewed_at=NOW),
    )


def test_reviewed_contact_requires_source(session):
    assert_rejected(
        session,
        Contact(full_name="A B", review_status="reviewed", collection_purpose="Inquiry",
                reviewed_by="cdo", reviewed_at=NOW),
    )


def test_reviewed_contact_requires_reviewer(session, new_observation):
    obs = new_observation()
    assert_rejected(
        session,
        Contact(full_name="A B", review_status="reviewed", collection_purpose="Inquiry",
                source_observation_id=obs.id),
    )


def test_reviewed_contact_with_full_evidence_accepted(session, new_observation):
    obs = new_observation()
    contact = make_contact(
        session, review_status="reviewed", collection_purpose="Inquiry",
        source_observation_id=obs.id, reviewed_by="cdo", reviewed_at=NOW,
    )
    assert contact.review_status == "reviewed"


def test_contact_blank_name_rejected(session):
    assert_rejected(session, Contact(full_name="   "))


def test_erased_status_requires_timestamp(session):
    assert_rejected(session, Contact(full_name="[erased]", review_status="erased"))


def test_contact_retention_date_defaults_about_a_year_out(session):
    value = session.execute(
        text("INSERT INTO core.contacts (full_name) VALUES ('Raw Person') "
             "RETURNING retention_review_at")
    ).scalar_one()
    assert value > datetime.now(timezone.utc) + timedelta(days=300)


# ---------- affiliations ----------

def test_affiliation_department_must_belong_to_same_org(session, org, new_observation):
    obs = new_observation()
    contact = make_contact(session)
    other = Organization(name="Other Org", normalized_name="other org", org_type="ngo")
    session.add(other)
    session.flush()
    dept = Department(organization_id=other.id, name="Linguistics")
    session.add(dept)
    session.flush()
    assert_rejected(
        session,
        ContactAffiliation(contact_id=contact.id, organization_id=org.id,
                           department_id=dept.id, source_observation_id=obs.id),
    )


def test_affiliation_with_matching_department_accepted(session, org, new_observation):
    obs = new_observation()
    contact = make_contact(session)
    dept = Department(organization_id=org.id, name="Linguistics")
    session.add(dept)
    session.flush()
    session.add(ContactAffiliation(contact_id=contact.id, organization_id=org.id,
                                   department_id=dept.id, source_observation_id=obs.id))
    session.flush()


def test_duplicate_affiliation_without_department_rejected(session, org, new_observation):
    obs = new_observation()
    contact = make_contact(session)
    session.add(ContactAffiliation(contact_id=contact.id, organization_id=org.id,
                                   source_observation_id=obs.id))
    session.flush()
    assert_rejected(
        session,
        ContactAffiliation(contact_id=contact.id, organization_id=org.id,
                           source_observation_id=obs.id),
    )


def test_person_can_have_affiliations_in_two_organizations(session, org, new_observation):
    obs = new_observation()
    contact = make_contact(session)
    other = Organization(name="Other Org", normalized_name="other org", org_type="ngo")
    session.add(other)
    session.flush()
    session.add_all([
        ContactAffiliation(contact_id=contact.id, organization_id=org.id,
                           role_title="Professor", source_observation_id=obs.id),
        ContactAffiliation(contact_id=contact.id, organization_id=other.id,
                           role_title="Advisor", source_observation_id=obs.id),
    ])
    session.flush()


# ---------- contact methods ----------

def test_method_needs_exactly_one_owner(session, org, new_observation):
    obs = new_observation()
    contact = make_contact(session)
    base = dict(method_type="email", value="a@b.ph", normalized_value="a@b.ph",
                collection_tier=2, source_observation_id=obs.id)
    assert_rejected(session, ContactMethod(**base))
    assert_rejected(session, ContactMethod(**base, contact_id=contact.id,
                                           organization_id=org.id))


def test_official_inbox_cannot_belong_to_a_person(session, new_observation):
    obs = new_observation()
    contact = make_contact(session)
    assert_rejected(
        session, make_person_method(contact, obs, collection_tier=1, is_official_inbox=True)
    )


def test_tier_one_must_be_official_inbox(session, org, new_observation):
    obs = new_observation()
    assert_rejected(session, make_org_method(org, obs, is_official_inbox=False))


def test_tier_three_must_belong_to_a_person(session, org, new_observation):
    obs = new_observation()
    assert_rejected(
        session, make_org_method(org, obs, collection_tier=3, is_official_inbox=False)
    )


def test_method_requires_source_observation(session, org):
    assert_rejected(
        session,
        ContactMethod(method_type="email", value="a@b.ph", normalized_value="a@b.ph",
                      collection_tier=1, is_official_inbox=True, organization_id=org.id),
    )


def test_method_defaults_are_unverified_at_database_level(session, org, new_observation):
    obs = new_observation()
    row = session.execute(
        text("INSERT INTO core.contact_methods (organization_id, method_type, value, "
             "normalized_value, collection_tier, is_official_inbox, source_observation_id) "
             "VALUES (:o, 'email', 'x@y.ph', 'x@y.ph', 1, true, :s) "
             "RETURNING syntax_valid, verification_status, review_status"),
        {"o": org.id, "s": obs.id},
    ).one()
    assert tuple(row) == (False, "unverified", "unreviewed")


def test_cannot_verify_without_valid_syntax(session, org, new_observation):
    obs = new_observation()
    assert_rejected(
        session,
        make_org_method(org, obs, syntax_valid=False, verification_status="verified",
                        verified_at=NOW, verified_by="cdo"),
    )


def test_cannot_verify_without_evidence(session, org, new_observation):
    obs = new_observation()
    assert_rejected(
        session,
        make_org_method(org, obs, syntax_valid=True, verification_status="verified"),
    )


def test_verified_with_evidence_accepted(session, org, new_observation):
    obs = new_observation()
    method = make_org_method(org, obs, syntax_valid=True, verification_status="verified",
                             verified_at=NOW, verified_by="cdo")
    session.add(method)
    session.flush()
    assert method.verification_status == "verified"


def test_duplicate_normalized_email_rejected(session, org, new_observation):
    obs = new_observation()
    session.add(make_org_method(org, obs))
    session.flush()
    assert_rejected(session, make_org_method(org, obs))


def test_email_must_be_stored_lowercase(session, org, new_observation):
    obs = new_observation()
    assert_rejected(session, make_org_method(org, obs, normalized_value="Registrar@Example.edu.ph"))


# ---------- suppression table rules ----------

def test_duplicate_active_suppression_rejected(session):
    session.add(make_suppression())
    session.flush()
    assert_rejected(session, make_suppression())


def test_suppression_can_be_recreated_after_lift(session):
    first = make_suppression()
    session.add(first)
    session.flush()
    first.status = "lifted"
    first.lifted_at = NOW
    first.lifted_by = "cdo"
    first.lift_reason = "Person asked to be contacted again"
    session.flush()
    session.add(make_suppression())
    session.flush()


def test_lifting_requires_audit_fields(session):
    assert_rejected(session, make_suppression(status="lifted", lifted_at=NOW))
    assert_rejected(session, make_suppression(status="lifted", lifted_by="cdo",
                                              lift_reason="because"))


def test_suppression_rows_cannot_be_deleted(session):
    entry = make_suppression()
    session.add(entry)
    session.flush()
    assert_sql_rejected(session, "DELETE FROM core.suppression_list WHERE id = :id",
                        {"id": entry.id})


def test_suppressed_value_cannot_be_changed(session):
    entry = make_suppression()
    session.add(entry)
    session.flush()
    assert_sql_rejected(
        session,
        "UPDATE core.suppression_list SET normalized_value = 'other@example.edu.ph' "
        "WHERE id = :id",
        {"id": entry.id},
    )


def test_lifted_entry_is_immutable(session):
    entry = suppress(session, "email", "optout@example.edu.ph")
    lift_suppression(session, entry, lifted_by="cdo", lift_reason="Requested by the person")
    assert_sql_rejected(
        session,
        "UPDATE core.suppression_list SET status = 'active', lifted_at = NULL, "
        "lifted_by = NULL, lift_reason = NULL WHERE id = :id",
        {"id": entry.id},
    )


# ---------- suppression checks ----------

def test_add_suppression_is_idempotent(session):
    first = suppress(session, "email", "optout@example.edu.ph")
    second = suppress(session, "email", " OptOut@Example.EDU.ph ")
    assert first.id == second.id


def test_is_suppressed_matches_normalized_email(session):
    suppress(session, "email", "  OptOut@Example.EDU.ph ")
    assert is_suppressed(session, "email", "optout@example.edu.ph")
    assert is_suppressed(session, "email", "OPTOUT@example.edu.ph ")


def test_is_suppressed_matches_parent_domain(session):
    suppress(session, "domain", "up.edu.ph")
    assert is_suppressed(session, "email", "someone@linguistics.up.edu.ph")
    assert is_suppressed(session, "contact_form", "https://www.up.edu.ph/contact")


def test_is_suppressed_false_for_unlisted(session):
    suppress(session, "email", "optout@example.edu.ph")
    assert not is_suppressed(session, "email", "other@example.edu.ph")
    assert not is_suppressed(session, "email", "someone@different.edu.ph")


def test_lifting_unblocks_recipient(session):
    entry = suppress(session, "email", "optout@example.edu.ph")
    assert is_suppressed(session, "email", "optout@example.edu.ph")
    lift_suppression(session, entry, lifted_by="cdo", lift_reason="Requested by the person")
    assert not is_suppressed(session, "email", "optout@example.edu.ph")


def test_is_suppressed_fails_closed_on_garbage(session):
    with pytest.raises(ValueError):
        is_suppressed(session, "email", "not-an-email")
    with pytest.raises(ValueError):
        is_suppressed(session, "fax", "12345678")


# ---------- erasure ----------

def test_erase_contact_removes_personal_data_and_suppresses(session, org, new_observation):
    contact_obs = new_observation("contact", {"name": "Juan Dela Cruz", "email": "juan@example.edu.ph"})
    method_obs = new_observation("contact_method", {"email": "juan@example.edu.ph"})
    affil_obs = new_observation("contact", {"name": "Juan Dela Cruz", "role": "Professor"})
    entity_only_obs = new_observation("contact", {"name": "Juan Dela Cruz", "page": "staff list"})
    unrelated_obs = new_observation("organization", {"name": "Fixture Org"})

    contact = make_contact(session, collection_purpose="Language-resource inquiry",
                           source_observation_id=contact_obs.id)
    session.add(ContactAffiliation(contact_id=contact.id, organization_id=org.id,
                                   role_title="Professor", source_observation_id=affil_obs.id))
    method = make_person_method(contact, method_obs)
    session.add(method)
    session.flush()
    for obs in (contact_obs, affil_obs, entity_only_obs):
        obs.entity_id = contact.id
    method_obs.entity_id = method.id
    session.flush()

    assert erase_contact(session, contact.id, performed_by="cdo", request_channel="email") is True

    session.refresh(contact)
    assert contact.review_status == "erased"
    assert contact.full_name == "[erased]"
    assert contact.erased_at is not None
    assert contact.source_observation_id is None
    assert session.scalars(select(ContactMethod).where(ContactMethod.contact_id == contact.id)).all() == []
    assert session.scalars(select(ContactAffiliation).where(ContactAffiliation.contact_id == contact.id)).all() == []
    for obs in (contact_obs, method_obs, affil_obs, entity_only_obs):
        session.refresh(obs)
        assert obs.raw_payload == {"erased": True}
    session.refresh(unrelated_obs)
    assert unrelated_obs.raw_payload == {"name": "Fixture Org"}
    assert is_suppressed(session, "email", "juan@example.edu.ph")


def test_erase_contact_is_idempotent(session):
    contact = make_contact(session)
    assert erase_contact(session, contact.id, performed_by="cdo") is True
    assert erase_contact(session, contact.id, performed_by="cdo") is False