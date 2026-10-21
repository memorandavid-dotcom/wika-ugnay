import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from ugnay.db.models_outreach import (
    Campaign,
    OpportunityEvidence,
    OutreachActivity,
    PartnershipOpportunity,
)
from ugnay.db.models_people import Contact, ContactMethod
from ugnay.db.models_resources import LanguageResource
from ugnay.db.repository import erase_contact
from ugnay.outreach.suppression import add_suppression

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


def make_campaign(session, **overrides):
    data = dict(name=f"campaign-{uuid.uuid4()}", purpose="Language-resource partnership inquiry",
                created_by="cdo")
    data.update(overrides)
    campaign = Campaign(**data)
    session.add(campaign)
    session.flush()
    return campaign


def make_live_campaign(session):
    return make_campaign(session, status="active", dry_run=False,
                         approved_by="adviser", approved_at=NOW)


def make_org_method(session, org, obs, **overrides):
    address = f"{uuid.uuid4().hex[:10]}@example.edu.ph"
    data = dict(method_type="email", value=address, normalized_value=address,
                collection_tier=1, is_official_inbox=True, organization_id=org.id,
                source_observation_id=obs.id, review_status="reviewed")
    data.update(overrides)
    method = ContactMethod(**data)
    session.add(method)
    session.flush()
    return method


def make_opportunity(session, org, **overrides):
    data = dict(organization_id=org.id, objective="institutional_partnership",
                stage="under_review")
    data.update(overrides)
    opp = PartnershipOpportunity(**data)
    session.add(opp)
    session.flush()
    return opp


def add_evidence(session, opp, obs):
    session.add(OpportunityEvidence(opportunity_id=opp.id, source_observation_id=obs.id))
    session.flush()


def qualify(session, opp, obs, stage="approved_for_outreach"):
    add_evidence(session, opp, obs)
    opp.stage = stage
    opp.qualification_reason = "Publishes Philippine-language materials"
    opp.qualified_by = "cdo"
    opp.qualified_at = NOW
    opp.score_explanation = "Strong relevance; evidence from the official site"
    session.flush()


def make_activity(session, campaign, opp, method, **overrides):
    data = dict(campaign_id=campaign.id, opportunity_id=opp.id, contact_method_id=method.id,
                assigned_to="cdo", purpose="Language-resource inquiry",
                subject="Partnership inquiry", draft_body="Dear Registrar, we would like to ...")
    data.update(overrides)
    activity = OutreachActivity(**data)
    session.add(activity)
    session.flush()
    return activity


def approve(session, activity):
    activity.status = "approved"
    activity.approved_by = "cdo"
    activity.approved_at = NOW
    session.flush()


def send(session, activity):
    activity.status = "sent"
    activity.sent_at = NOW
    session.flush()


def suppress(session, value_type, value):
    add_suppression(session, value_type=value_type, value=value, reason="opt_out",
                    request_received_at=NOW, added_by="cdo")


@pytest.fixture
def ctx(session, org, new_observation):
    obs = new_observation("organization")
    opp = make_opportunity(session, org)
    qualify(session, opp, obs)
    return SimpleNamespace(
        org=org, obs=obs, opp=opp,
        method=make_org_method(session, org, obs),
        campaign=make_campaign(session),
    )


# ---------- opportunities ----------

def test_outreach_tables_exist(session):
    found = set(inspect(session.connection()).get_table_names(schema="core"))
    assert {"partnership_opportunities", "opportunity_evidence", "campaigns",
            "outreach_activities"} <= found


def test_opportunity_defaults_at_database_level(session, org):
    row = session.execute(
        text("INSERT INTO core.partnership_opportunities (organization_id, objective) "
             "VALUES (:o, 'institutional_partnership') RETURNING stage, total_score"),
        {"o": org.id},
    ).one()
    assert tuple(row) == ("discovered", 0)


@pytest.mark.parametrize("column,too_high", [
    ("score_relevance", 41), ("score_potential", 26),
    ("score_language", 21), ("score_evidence", 16),
])
def test_score_components_are_range_checked(session, org, column, too_high):
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(PartnershipOpportunity(
            organization_id=org.id, objective="institutional_partnership",
            **{column: too_high}))
        session.flush()


def test_total_score_is_computed_by_the_database(session, org):
    opp = make_opportunity(session, org, score_relevance=30, score_potential=20,
                           score_language=10, score_evidence=5)
    session.refresh(opp)
    assert opp.total_score == 65


def test_qualified_requires_reason_and_explanation(session, org, new_observation):
    opp = make_opportunity(session, org)
    add_evidence(session, opp, new_observation("organization"))
    with expect_db_error(session, CHECK_VIOLATION):
        opp.stage = "qualified"
        session.flush()


def test_qualified_requires_evidence_row(session, org):
    opp = make_opportunity(session, org)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        opp.stage = "qualified"
        opp.qualification_reason = "Looks relevant"
        opp.qualified_by = "cdo"
        opp.qualified_at = NOW
        opp.score_explanation = "Scored by hand"
        session.flush()


def test_qualification_succeeds_with_reason_and_evidence(session, ctx):
    session.refresh(ctx.opp)
    assert ctx.opp.stage == "approved_for_outreach"


def test_resource_link_only_for_acquisition(session, org):
    resource = LanguageResource(title="Dictionary", resource_type="dictionary",
                                access_url=f"https://example.edu.ph/{uuid.uuid4()}")
    session.add(resource)
    session.flush()
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(PartnershipOpportunity(
            organization_id=org.id, objective="institutional_partnership",
            resource_id=resource.id))
        session.flush()


def test_duplicate_open_opportunity_rejected(session, org):
    make_opportunity(session, org)
    with expect_db_error(session, UNIQUE_VIOLATION):
        session.add(PartnershipOpportunity(
            organization_id=org.id, objective="institutional_partnership"))
        session.flush()


def test_new_opportunity_allowed_after_previous_declined(session, org):
    make_opportunity(session, org, stage="declined", closed_reason="Not relevant")
    make_opportunity(session, org)


def test_declined_requires_reason(session, org):
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(PartnershipOpportunity(
            organization_id=org.id, objective="institutional_partnership",
            stage="declined"))
        session.flush()


def test_cannot_delete_last_evidence_of_qualified_opportunity(session, ctx):
    with expect_db_error(session, RAISED_BY_TRIGGER):
        session.execute(
            text("DELETE FROM core.opportunity_evidence WHERE opportunity_id = :o"),
            {"o": ctx.opp.id},
        )


# ---------- campaigns ----------

def test_campaign_name_must_be_unique(session):
    first = make_campaign(session)
    with expect_db_error(session, UNIQUE_VIOLATION):
        session.add(Campaign(name=first.name, purpose="Another purpose", created_by="cdo"))
        session.flush()


def test_campaign_defaults_to_dry_run_draft(session):
    row = session.execute(
        text("INSERT INTO core.campaigns (name, purpose, created_by) "
             "VALUES ('raw campaign', 'purpose', 'cdo') RETURNING dry_run, status")
    ).one()
    assert tuple(row) == (True, "draft")


def test_live_campaign_requires_approval(session):
    with expect_db_error(session, CHECK_VIOLATION):
        session.add(Campaign(name=f"c-{uuid.uuid4()}", purpose="Purpose",
                             created_by="cdo", dry_run=False))
        session.flush()


# ---------- outreach activities ----------

def test_activity_must_start_as_drafted(session, ctx):
    with expect_db_error(session, RAISED_BY_TRIGGER):
        make_activity(session, ctx.campaign, ctx.opp, ctx.method, status="approved",
                      approved_by="cdo", approved_at=NOW)


def test_approval_requires_approver_fields(session, ctx):
    activity = make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    with expect_db_error(session, CHECK_VIOLATION):
        activity.status = "approved"
        session.flush()


def test_sent_requires_timestamp(session, ctx):
    activity = make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    approve(session, activity)
    with expect_db_error(session, CHECK_VIOLATION):
        activity.status = "sent"
        session.flush()


def test_cannot_skip_approval(session, ctx):
    activity = make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        send(session, activity)


def test_cancelled_is_terminal(session, ctx):
    activity = make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    activity.status = "cancelled"
    session.flush()
    with expect_db_error(session, RAISED_BY_TRIGGER):
        approve(session, activity)


def test_duplicate_recipient_in_one_campaign_rejected(session, ctx):
    make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    with expect_db_error(session, UNIQUE_VIOLATION):
        make_activity(session, ctx.campaign, ctx.opp, ctx.method)


def test_only_one_pending_message_per_recipient(session, ctx):
    make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    with expect_db_error(session, UNIQUE_VIOLATION):
        make_activity(session, make_campaign(session), ctx.opp, ctx.method)


def test_approved_content_is_locked(session, ctx):
    activity = make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    approve(session, activity)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        activity.draft_body = "Changed after approval"
        session.flush()


def test_suppressed_recipient_cannot_be_approved(session, ctx):
    activity = make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    suppress(session, "email", ctx.method.normalized_value)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        approve(session, activity)


def test_domain_suppression_blocks_send(session, ctx):
    activity = make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    approve(session, activity)
    suppress(session, "domain", "example.edu.ph")
    with expect_db_error(session, RAISED_BY_TRIGGER):
        send(session, activity)


def test_dry_run_send_succeeds(session, ctx):
    activity = make_activity(session, ctx.campaign, ctx.opp, ctx.method)
    approve(session, activity)
    send(session, activity)
    session.refresh(activity)
    assert activity.status == "sent" and activity.is_dry_run is True


def test_real_send_blocked_when_campaign_is_dry_run(session, ctx):
    activity = make_activity(session, ctx.campaign, ctx.opp, ctx.method, is_dry_run=False)
    approve(session, activity)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        send(session, activity)


def test_real_send_blocked_when_method_unreviewed(session, ctx):
    method = make_org_method(session, ctx.org, ctx.obs, review_status="unreviewed")
    activity = make_activity(session, make_live_campaign(session), ctx.opp, method,
                             is_dry_run=False)
    approve(session, activity)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        send(session, activity)


def test_real_send_blocked_when_opportunity_not_approved(session, ctx):
    opp = make_opportunity(session, ctx.org, objective="resource_acquisition")
    qualify(session, opp, ctx.obs, stage="qualified")
    activity = make_activity(session, make_live_campaign(session), opp, ctx.method,
                             is_dry_run=False)
    approve(session, activity)
    with expect_db_error(session, RAISED_BY_TRIGGER):
        send(session, activity)


def test_real_send_succeeds_when_every_check_passes(session, ctx):
    activity = make_activity(session, make_live_campaign(session), ctx.opp, ctx.method,
                             is_dry_run=False)
    approve(session, activity)
    send(session, activity)
    session.refresh(activity)
    assert activity.status == "sent" and activity.is_dry_run is False


# ---------- erasure ----------

def test_erasure_scrubs_outreach_and_cancels_unsent(session, ctx):
    contact = Contact(full_name="Juan Dela Cruz")
    session.add(contact)
    session.flush()
    method = ContactMethod(
        method_type="email", value="juan@example.edu.ph", normalized_value="juan@example.edu.ph",
        collection_tier=3, is_official_inbox=False, contact_id=contact.id,
        source_observation_id=ctx.obs.id)
    session.add(method)
    session.flush()

    sent = make_activity(session, ctx.campaign, ctx.opp, method)
    approve(session, sent)
    send(session, sent)
    pending = make_activity(session, make_campaign(session), ctx.opp, method)

    assert erase_contact(session, contact.id, performed_by="cdo") is True

    session.refresh(sent)
    session.refresh(pending)
    assert sent.status == "sent"
    assert sent.draft_body == "[erased]" and sent.contact_method_id is None
    assert pending.status == "cancelled" and pending.draft_body == "[erased]"