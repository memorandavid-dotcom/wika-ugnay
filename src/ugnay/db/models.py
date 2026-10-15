"""SQLAlchemy models, part A: source tracking, languages, organizations."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ugnay.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, in_list_check
from ugnay.db.constants import (
    COLLECTION_METHODS,
    OBSERVATION_ENTITY_TYPES,
    ORG_TYPES,
    PUBLICATION_STATUSES,
    QUALIFICATION_STATUSES,
    RUN_STATUSES,
    SOURCE_CATEGORIES,
    SOURCE_REVIEW_STATUSES,
)


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(60), nullable=False)
    collection_method: Mapped[str] = mapped_column(String(40), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    terms_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_interval_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=168, server_default=text("168")
    )
    requests_per_minute: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10")
    )
    max_response_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5_000_000, server_default=text("5000000")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    use_notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("name"),
        in_list_check("category", SOURCE_CATEGORIES, "category_valid"),
        in_list_check("collection_method", COLLECTION_METHODS, "method_valid"),
        in_list_check("review_status", SOURCE_REVIEW_STATUSES, "review_status_valid"),
        CheckConstraint("url ~ '^https?://'", name="url_is_http"),
        CheckConstraint("refresh_interval_hours > 0", name="refresh_positive"),
        CheckConstraint("requests_per_minute > 0", name="rate_positive"),
        CheckConstraint("max_response_bytes > 0", name="max_bytes_positive"),
        CheckConstraint(
            "NOT enabled OR (review_status = 'approved' AND terms_reviewed_at IS NOT NULL)",
            name="enabled_requires_review",
        ),
    )


class IngestionRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_runs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.sources.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", server_default="running"
    )
    records_fetched: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    records_new: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    records_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    records_quarantined: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    error_summary: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        in_list_check("status", RUN_STATUSES, "status_valid"),
        CheckConstraint(
            "records_fetched >= 0 AND records_new >= 0 "
            "AND records_updated >= 0 AND records_quarantined >= 0",
            name="counts_non_negative",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="finish_after_start",
        ),
        Index("ix_ingestion_runs_source_started", "source_id", "started_at"),
    )


class SourceObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_observations"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.sources.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.ingestion_runs.id", ondelete="SET NULL")
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column()  # polymorphic: no FK
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        in_list_check("entity_type", OBSERVATION_ENTITY_TYPES, "entity_type_valid"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="hash_is_sha256_hex"),
        CheckConstraint("length(source_url) <= 2000", name="url_length"),
        UniqueConstraint("source_id", "source_url", "content_hash"),
        Index("ix_source_observations_entity", "entity_type", "entity_id"),
        Index("ix_source_observations_run", "run_id"),
    )


class Language(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "languages"

    iso639_3: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    family: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("iso639_3"),
        CheckConstraint("iso639_3 ~ '^[a-z]{3}$'", name="iso_format"),
    )


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    website_url: Mapped[str | None] = mapped_column(Text)
    org_type: Mapped[str] = mapped_column(String(40), nullable=False)
    region: Mapped[str | None] = mapped_column(String(100))
    qualification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="discovered", server_default="discovered"
    )
    publication_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private", server_default="private"
    )
    date_last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("domain"),
        in_list_check("org_type", ORG_TYPES, "org_type_valid"),
        in_list_check(
            "qualification_status", QUALIFICATION_STATUSES, "qualification_valid"
        ),
        in_list_check("publication_status", PUBLICATION_STATUSES, "publication_valid"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("domain IS NULL OR domain = lower(domain)", name="domain_lowercase"),
        Index("ix_organizations_normalized_name", "normalized_name"),
    )


class Department(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "departments"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("id", "organization_id"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
    )


class OrganizationLanguage(Base):
    """Junction table: which languages an organization works with.

    Composite primary key instead of a UUID, because the pair itself is the identity.
    """

    __tablename__ = "organization_languages"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.organizations.id", ondelete="RESTRICT"), primary_key=True
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


from ugnay.db import models_people  # noqa: E402,F401  (registers people tables)