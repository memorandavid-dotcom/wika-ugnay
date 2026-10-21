"""Repository functions. More are added in later phases."""
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from ugnay.db.models import SourceObservation
from ugnay.db.models_outreach import OutreachActivity
from ugnay.db.models_people import Contact, ContactAffiliation, ContactMethod
from ugnay.outreach.suppression import add_suppression

ERASED_NAME = "[erased]"


def erase_contact(
    session: Session,
    contact_id: uuid.UUID,
    *,
    performed_by: str,
    request_channel: str | None = None,
    request_received_at: datetime | None = None,
) -> bool:
    """Erase a person's personal data but keep a suppression entry.

    Returns False if the contact was already erased. The caller owns the transaction.
    """
    contact = session.execute(
        select(Contact).where(Contact.id == contact_id).with_for_update()
    ).scalar_one_or_none()
    if contact is None:
        raise LookupError(f"contact {contact_id} not found")
    if contact.review_status == "erased":
        return False

    now = datetime.now(timezone.utc)
    received = request_received_at or now

    methods = session.execute(
        select(ContactMethod).where(ContactMethod.contact_id == contact.id)
    ).scalars().all()
    affiliations = session.execute(
        select(ContactAffiliation).where(ContactAffiliation.contact_id == contact.id)
    ).scalars().all()

    # 1. Keep the person blocked so a later ingestion cannot quietly re-add them.
    for method in methods:
        if method.method_type in ("email", "phone"):
            add_suppression(
                session,
                value_type=method.method_type,
                value=method.normalized_value,
                reason="erasure_request",
                request_received_at=received,
                request_channel=request_channel,
                added_by=performed_by,
            )

    # 2. Scrub the stored evidence (raw payloads contain the personal fields).
    method_ids = [m.id for m in methods]
    observation_ids = {
        contact.source_observation_id,
        *(m.source_observation_id for m in methods),
        *(a.source_observation_id for a in affiliations),
    } - {None}
    conditions = [
        and_(SourceObservation.entity_type == "contact", SourceObservation.entity_id == contact.id)
    ]
    if method_ids:
        conditions.append(
            and_(
                SourceObservation.entity_type == "contact_method",
                SourceObservation.entity_id.in_(method_ids),
            )
        )
    if observation_ids:
        conditions.append(SourceObservation.id.in_(observation_ids))
    observations = session.execute(
        select(SourceObservation).where(or_(*conditions))
    ).scalars().all()
    for obs in observations:
        obs.raw_payload = {"erased": True}
        # The old hash is a guessable fingerprint of personal data, so replace it.
        obs.content_hash = hashlib.sha256(f"erased:{obs.id}".encode()).hexdigest()
    session.flush()

    # 2b. Scrub outreach drafts to this person and cancel anything not yet sent.
    if method_ids:
        session.execute(
            update(OutreachActivity)
            .where(OutreachActivity.contact_method_id.in_(method_ids))
            .values(draft_body=ERASED_NAME, subject=ERASED_NAME)
            .execution_options(synchronize_session=False)
        )
        session.execute(
            update(OutreachActivity)
            .where(
                OutreachActivity.contact_method_id.in_(method_ids),
                OutreachActivity.status.in_(("drafted", "approved")),
            )
            .values(status="cancelled")
            .execution_options(synchronize_session=False)
        )
        session.flush()

    # 3. Remove the person's methods and affiliations.
    session.execute(delete(ContactMethod).where(ContactMethod.contact_id == contact.id))
    session.execute(
        delete(ContactAffiliation).where(ContactAffiliation.contact_id == contact.id)
    )

    # 4. Blank the contact row itself (the row stays so history keeps its links).
    contact.full_name = ERASED_NAME
    contact.review_status = "erased"
    contact.erased_at = now
    contact.source_observation_id = None
    contact.reviewed_by = None
    contact.reviewed_at = None
    session.flush()
    return True