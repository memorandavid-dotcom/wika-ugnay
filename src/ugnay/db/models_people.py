"""SQLAlchemy models, part B: contacts, contact methods, suppression."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ugnay.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, in_list_check
from ugnay.db.constants import (
    CONTACT_REVIEW_STATUSES,
    METHOD_REVIEW_STATUSES,
    METHOD_TYPES,
    REQUEST_CHANNELS,
    SUPPRESSION_REASONS,
    SUPPRESSION_STATUSES,
    SUPPRESSION_VALUE_TYPES,
    VERIFICATION_STATUSES,
)

RETENTION_DEFAULT = text("now() + interval '12 months'")


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named person. Roles live on ContactAffiliation, methods on ContactMethod."""

    __tablename__ = "contacts"

    full_name: Mapped[str] = mapped_column(String(300), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unreviewed", server_default="unreviewed"
    )
    collection_purpose: Mapped[str | None] = mapped_column(Text)
    source_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.source_observations.id", ondelete="RESTRICT")
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_review_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=RETENTION_DEFAULT
    )
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        in_list_check("review_status", CONTACT_REVIEW_STATUSES, "review_status_valid"),
        CheckConstraint("btrim(full_name) <> ''", name="name_not_blank"),
        CheckConstraint(
            "review_status <> 'reviewed' OR ("
            "collection_purpose IS NOT NULL AND btrim(collection_purpose) <> '' "
            "AND source_observation_id IS NOT NULL "
            "AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="reviewed_requires_evidence",
        ),
        CheckConstraint(
            "(review_status = 'erased') = (erased_at IS NOT NULL)",
            name="erased_consistent",
        ),
        CheckConstraint(
            "review_status <> 'erased' OR full_name = '[erased]'",
            name="erased_name_cleared",
        ),
        Index("ix_contacts_retention_review_at", "retention_review_at"),
    )


class ContactAffiliation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contact_affiliations"

    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.contacts.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column()  # FK is composite, below
    role_title: Mapped[str | None] = mapped_column(String(300))
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    source_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_observations.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        # Guarantees the department belongs to the same organization.
        # If department_id is NULL the check is skipped (standard MATCH SIMPLE).
        ForeignKeyConstraint(
            ["department_id", "organization_id"],
            ["core.departments.id", "core.departments.organization_id"],
            ondelete="RESTRICT",
            name="fk_affiliation_department_org",
        ),
        # Two partial indexes because Postgres treats NULLs as distinct in UNIQUE.
        Index(
            "uq_affiliation_no_department",
            "contact_id",
            "organization_id",
            unique=True,
            postgresql_where=text("department_id IS NULL"),
        ),
        Index(
            "uq_affiliation_with_department",
            "contact_id",
            "organization_id",
            "department_id",
            unique=True,
            postgresql_where=text("department_id IS NOT NULL"),
        ),
        Index("ix_contact_affiliations_organization_id", "organization_id"),
    )


class ContactMethod(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An email, phone, or contact form. Owned by a person OR an organization."""

    __tablename__ = "contact_methods"

    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.contacts.id", ondelete="RESTRICT")
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.organizations.id", ondelete="RESTRICT")
    )
    method_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # as published
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    collection_tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_official_inbox: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    syntax_valid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unverified", server_default="unverified"
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(String(100))
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unreviewed", server_default="unreviewed"
    )
    source_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_observations.id", ondelete="RESTRICT"), nullable=False
    )
    date_last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_review_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=RETENTION_DEFAULT
    )

    __table_args__ = (
        UniqueConstraint("method_type", "normalized_value"),
        in_list_check("method_type", METHOD_TYPES, "method_type_valid"),
        in_list_check("verification_status", VERIFICATION_STATUSES, "verification_valid"),
        in_list_check("review_status", METHOD_REVIEW_STATUSES, "review_status_valid"),
        CheckConstraint("num_nonnulls(contact_id, organization_id) = 1", name="exactly_one_owner"),
        CheckConstraint("collection_tier IN (1, 2, 3)", name="tier_valid"),
        CheckConstraint(
            "(collection_tier = 1) = is_official_inbox", name="tier_matches_official_flag"
        ),
        CheckConstraint(
            "NOT is_official_inbox OR organization_id IS NOT NULL",
            name="official_inbox_belongs_to_org",
        ),
        CheckConstraint(
            "collection_tier <> 3 OR contact_id IS NOT NULL", name="tier3_requires_person"
        ),
        CheckConstraint(
            "normalized_value = btrim(normalized_value) AND btrim(normalized_value) <> ''",
            name="normalized_trimmed",
        ),
        CheckConstraint(
            "method_type <> 'email' OR normalized_value = lower(normalized_value)",
            name="email_lowercase",
        ),
        CheckConstraint(
            "verification_status <> 'verified' OR "
            "(syntax_valid AND verified_at IS NOT NULL AND verified_by IS NOT NULL)",
            name="verified_requires_evidence",
        ),
        Index("ix_contact_methods_contact_id", "contact_id"),
        Index("ix_contact_methods_organization_id", "organization_id"),
        Index("ix_contact_methods_retention_review_at", "retention_review_at"),
    )


class SuppressionEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppression_list"

    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    request_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    request_channel: Mapped[str | None] = mapped_column(String(20))
    request_note: Mapped[str | None] = mapped_column(Text)  # never paste a full email here
    added_by: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="active", server_default="active"
    )
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lifted_by: Mapped[str | None] = mapped_column(String(100))
    lift_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        in_list_check("value_type", SUPPRESSION_VALUE_TYPES, "value_type_valid"),
        in_list_check("reason", SUPPRESSION_REASONS, "reason_valid"),
        in_list_check("status", SUPPRESSION_STATUSES, "status_valid"),
        in_list_check("request_channel", REQUEST_CHANNELS, "channel_valid"),
        CheckConstraint(
            "normalized_value <> '' AND normalized_value = btrim(normalized_value) "
            "AND normalized_value = lower(normalized_value)",
            name="normalized_clean",
        ),
        CheckConstraint(
            "(status = 'lifted') = (lifted_at IS NOT NULL)", name="lift_timestamp_consistent"
        ),
        CheckConstraint(
            "status <> 'lifted' OR (lifted_by IS NOT NULL AND btrim(lifted_by) <> '' "
            "AND lift_reason IS NOT NULL AND btrim(lift_reason) <> '')",
            name="lifted_requires_audit",
        ),
        # Only one ACTIVE entry per value; lifted rows stay as history.
        Index(
            "uq_suppression_active_value",
            "value_type",
            "normalized_value",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )