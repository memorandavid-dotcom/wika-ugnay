"""SQLAlchemy models, part C: language resources, rights reviews, links."""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from ugnay.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, in_list_check
from ugnay.db.constants import (
    DOWNLOAD_STATUSES,
    EXTRACTION_STATUSES,
    OBSERVATION_ROLES,
    PERMISSION_STATUSES,
    PERMITTED_USES,
    PRODUCTION_STATUSES,
    PUBLICATION_STATUSES,
    RESOURCE_TYPES,
)

_USES_SQL = ", ".join("'" + use + "'" for use in PERMITTED_USES)


class LanguageResource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "language_resources"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    publisher_name: Mapped[str | None] = mapped_column(String(300))  # as stated by source
    custodian_org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.organizations.id", ondelete="RESTRICT")
    )
    access_url: Mapped[str] = mapped_column(Text, nullable=False)
    publication_year: Mapped[int | None] = mapped_column(SmallInteger)

    download_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_downloaded", server_default="not_downloaded"
    )
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    local_path: Mapped[str | None] = mapped_column(Text)  # relative to data/raw, forward slashes

    extraction_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_extracted", server_default="not_extracted"
    )
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    production_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_approved", server_default="not_approved"
    )
    publication_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private", server_default="private"
    )
    date_last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("access_url"),
        in_list_check("resource_type", RESOURCE_TYPES, "resource_type_valid"),
        in_list_check("download_status", DOWNLOAD_STATUSES, "download_status_valid"),
        in_list_check("extraction_status", EXTRACTION_STATUSES, "extraction_status_valid"),
        in_list_check("production_status", PRODUCTION_STATUSES, "production_status_valid"),
        in_list_check("publication_status", PUBLICATION_STATUSES, "publication_valid"),
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint("access_url ~ '^https?://'", name="access_url_is_http"),
        CheckConstraint(
            "publication_year IS NULL OR publication_year BETWEEN 1000 AND 2100",
            name="year_plausible",
        ),
        CheckConstraint(
            "file_sha256 IS NULL OR file_sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"
        ),
        CheckConstraint(
            "local_path IS NULL OR "
            "(local_path !~ '^(/|[A-Za-z][:])' AND local_path !~ '[.][.]')",
            name="local_path_relative",
        ),
        CheckConstraint(
            "download_status <> 'downloaded' OR (file_sha256 IS NOT NULL "
            "AND downloaded_at IS NOT NULL AND local_path IS NOT NULL)",
            name="downloaded_requires_evidence",
        ),
        CheckConstraint(
            "extraction_status <> 'extracted' OR download_status = 'downloaded'",
            name="extraction_requires_download",
        ),
        CheckConstraint(
            "extraction_status <> 'extracted' OR extracted_at IS NOT NULL",
            name="extracted_requires_timestamp",
        ),
        CheckConstraint(
            "production_status <> 'approved_for_production' OR extraction_status = 'extracted'",
            name="production_requires_extraction",
        ),
        Index("ix_language_resources_custodian_org_id", "custodian_org_id"),
    )


class ResourceRightsReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only. A trigger blocks UPDATE and DELETE (migration 0006)."""

    __tablename__ = "resource_rights_reviews"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.language_resources.id", ondelete="RESTRICT"), nullable=False
    )
    # Insertion order. The newest review (highest value) is the one that counts.
    review_seq: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False
    )
    license: Mapped[str | None] = mapped_column(String(200))
    permission_status: Mapped[str] = mapped_column(String(20), nullable=False)
    permitted_uses: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    reviewer: Mapped[str] = mapped_column(String(100), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_url: Mapped[str | None] = mapped_column(Text)
    evidence_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        in_list_check("permission_status", PERMISSION_STATUSES, "status_valid"),
        CheckConstraint(
            f"permitted_uses <@ ARRAY[{_USES_SQL}]::varchar[]", name="permitted_uses_valid"
        ),
        CheckConstraint(
            "permission_status <> 'approved' OR cardinality(permitted_uses) >= 1",
            name="approved_requires_use",
        ),
        CheckConstraint(
            "permission_status NOT IN ('unknown', 'pending_request', 'denied', 'revoked') "
            "OR cardinality(permitted_uses) = 0",
            name="no_uses_unless_granted",
        ),
        CheckConstraint(
            "permission_status NOT IN ('approved', 'restricted') "
            "OR evidence_url IS NOT NULL "
            "OR (evidence_note IS NOT NULL AND btrim(evidence_note) <> '')",
            name="grant_requires_evidence",
        ),
        CheckConstraint(
            "evidence_url IS NULL OR evidence_url ~ '^https?://'", name="evidence_url_is_http"
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > reviewed_at", name="expiry_after_review"
        ),
        CheckConstraint("btrim(reviewer) <> ''", name="reviewer_not_blank"),
        Index("ix_resource_rights_reviews_resource_seq", "resource_id", "review_seq"),
    )


class ResourceLanguage(Base):
    __tablename__ = "resource_languages"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.language_resources.id", ondelete="RESTRICT"), primary_key=True
    )
    language_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.languages.id", ondelete="RESTRICT"), primary_key=True
    )
    source_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.source_observations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResourceObservation(Base):
    """Which source observations mention a resource (a resource can have many)."""

    __tablename__ = "resource_observations"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.language_resources.id", ondelete="RESTRICT"), primary_key=True
    )
    source_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_observations.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, default="discovery", server_default="discovery"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (in_list_check("role", OBSERVATION_ROLES, "role_valid"),)