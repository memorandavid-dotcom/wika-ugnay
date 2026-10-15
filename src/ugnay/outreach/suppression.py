"""Suppression checks. The sending service must call is_suppressed() itself."""
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ugnay.db.models_people import SuppressionEntry
from ugnay.processing.normalize import (
    normalize_contact_value,
    normalize_domain,
    normalize_email,
    normalize_phone,
)

_VALUE_NORMALIZERS = {
    "email": normalize_email,
    "phone": normalize_phone,
    "domain": normalize_domain,
}


def _domain_candidates(domain: str) -> list[str]:
    """a.b.edu.ph -> [a.b.edu.ph, b.edu.ph, edu.ph]. Never the bare TLD."""
    labels = domain.split(".")
    if len(labels) == 1:
        return [domain]
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]


def suppression_keys(method_type: str, value: str) -> list[tuple[str, str]]:
    normalized = normalize_contact_value(method_type, value)
    if method_type == "email":
        domain = normalized.split("@")[1]
        return [("email", normalized)] + [("domain", d) for d in _domain_candidates(domain)]
    if method_type == "phone":
        return [("phone", normalized)]
    if method_type == "contact_form":
        host = urlsplit(normalized).hostname
        if not host:
            raise ValueError("contact form URL has no host")
        return [("domain", d) for d in _domain_candidates(host)]
    raise ValueError(f"unsupported contact method type: {method_type!r}")


def is_suppressed(session: Session, method_type: str, value: str) -> bool:
    keys = suppression_keys(method_type, value)
    match_any = or_(
        *[
            and_(
                SuppressionEntry.value_type == value_type,
                SuppressionEntry.normalized_value == normalized,
            )
            for value_type, normalized in keys
        ]
    )
    stmt = (
        select(SuppressionEntry.id)
        .where(SuppressionEntry.status == "active", match_any)
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def add_suppression(
    session: Session,
    *,
    value_type: str,
    value: str,
    reason: str,
    request_received_at: datetime,
    added_by: str,
    request_channel: str | None = None,
    request_note: str | None = None,
) -> SuppressionEntry:
    """Idempotent: returns the existing active entry if there already is one."""
    try:
        normalized = _VALUE_NORMALIZERS[value_type](value)
    except KeyError:
        raise ValueError(f"unsupported suppression value type: {value_type!r}") from None

    existing = session.execute(
        select(SuppressionEntry).where(
            SuppressionEntry.status == "active",
            SuppressionEntry.value_type == value_type,
            SuppressionEntry.normalized_value == normalized,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    entry = SuppressionEntry(
        value_type=value_type,
        normalized_value=normalized,
        reason=reason,
        request_received_at=request_received_at,
        request_channel=request_channel,
        request_note=request_note,
        added_by=added_by,
    )
    session.add(entry)
    session.flush()
    return entry


def lift_suppression(
    session: Session,
    entry: SuppressionEntry,
    *,
    lifted_by: str,
    lift_reason: str,
    lifted_at: datetime | None = None,
) -> None:
    if entry.status != "active":
        raise ValueError("only active entries can be lifted")
    entry.status = "lifted"
    entry.lifted_at = lifted_at or datetime.now(timezone.utc)
    entry.lifted_by = lifted_by
    entry.lift_reason = lift_reason
    session.flush()