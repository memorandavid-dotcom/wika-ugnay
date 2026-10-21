"""SQLAlchemy models, part D: opportunities, campaigns, outreach activities."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ugnay.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, in_list_check
from ugnay.db.constants import (
    ACTIVITY_STATUSES,
    CAMPAIGN_STATUSES,
    OBJECTIVES,
    OPPORTUNITY_STAGES,
    QUALIFIED_STAGES,
)

_QUALIFIED_SQL = ", ".join("'" + s + "'" for s in QUALIFIED_STAGES)


class PartnershipOpportunity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "partnership_opportunities"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.language_resources.id", ondelete="RESTRICT")
    )
    objective: Mapped[str] = mapped_column(String(30), nullable=False)
    stage: Mapped[str] = mapped_column(
        String(30), nullable=False, default="discovered", server_default="discovered"
    )
    score_relevance: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    score_potential: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    score_language: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    score_evidence: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    total_score: Mapped[int] = mapped_column(
        SmallInteger,
        Computed(
            "score_relevance + score_potential + score_language + score_evidence",
            persisted=True,
        ),
    )
    score_explanation: Mapped[str | None] = mapped_column(Text)
    qualification_reason: Mapped[str | None] = mapped_column(Text)
    qualified_by: Mapped[str | None] = mapped_column(String(100))
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        in_list_check("objective", OBJECTIVES, "objective_valid"),
        in_list_check("stage", OPPORTUNITY_STAGES, "stage_valid"),
        CheckConstraint("score_relevance BETWEEN 0 AND 40", name="relevance_range"),
        CheckConstraint("score_potential BETWEEN 0 AND 25", name="potential_range"),
        CheckConstraint("score_language BETWEEN 0 AND 20", name="language_range"),
        CheckConstraint("score_evidence BETWEEN 0 AND 15", name="evidence_range"),
        CheckConstraint(
            "resource_id IS NULL OR objective = 'resource_acquisition'",
            name="resource_only_for_acquisition",
        ),
        CheckConstraint(
            f"stage NOT IN ({_QUALIFIED_SQL}) OR ("
            "qualification_reason IS NOT NULL AND btrim(qualification_reason) <> '' "
            "AND qualified_by IS NOT NULL AND btrim(qualified_by) <> '' "
            "AND qualified_at IS NOT NULL "
            "AND score_explanation IS NOT NULL AND btrim(score_explanation) <> '')",
            name="qualified_requires_basis",
        ),
        CheckConstraint(
            "stage NOT IN ('declined', 'closed') OR "
            "(closed_reason IS NOT NULL AND btrim(closed_reason) <> '')",
            name="closed_requires_reason",
        ),
        # One open opportunity per organization and objective (and resource, if any).
        Index(
            "uq_opportunity_open_org_objective",
            "organization_id",
            "objective",
            unique=True,
            postgresql_where=text("stage NOT IN ('declined', 'closed') AND resource_id IS NULL"),
        ),
        Index(
            "uq_opportunity_open_org_objective_resource",
            "organization_id",
            "objective",
            "resource_id",
            unique=True,
            postgresql_where=text(
                "stage NOT IN ('declined', 'closed') AND resource_id IS NOT NULL"
            ),
        ),
        Index("ix_partnership_opportunities_organization_id", "organization_id"),
        Index("ix_partnership_opportunities_stage", "stage"),
    )


class OpportunityEvidence(Base):
    """Source observations that justify an opportunity."""

    __tablename__ = "opportunity_evidence"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.partnership_opportunities.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    source_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_observations.id", ondelete="RESTRICT"), primary_key=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Campaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("name"),
        in_list_check("status", CAMPAIGN_STATUSES, "status_valid"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("btrim(purpose) <> ''", name="purpose_not_blank"),
        CheckConstraint(
            "dry_run OR (approved_by IS NOT NULL AND btrim(approved_by) <> '' "
            "AND approved_at IS NOT NULL)",
            name="live_requires_approval",
        ),
    )


class OutreachActivity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One planned or sent message to one contact method. Status rules: migration 0008."""

    __tablename__ = "outreach_activities"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.partnership_opportunities.id", ondelete="RESTRICT"), nullable=False
    )
    # SET NULL so erasing a contact can delete the method without losing history.
    contact_method_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.contact_methods.id", ondelete="SET NULL")
    )
    assigned_to: Mapped[str | None] = mapped_column(String(100))
    purpose: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(300))
    draft_body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="drafted", server_default="drafted"
    )
    is_dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meeting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_method_id"),
        in_list_check("status", ACTIVITY_STATUSES, "status_valid"),
        CheckConstraint("btrim(draft_body) <> ''", name="body_not_blank"),
        CheckConstraint(
            "status NOT IN ('approved', 'sent', 'replied', 'meeting_scheduled') OR ("
            "approved_by IS NOT NULL AND btrim(approved_by) <> '' "
            "AND approved_at IS NOT NULL "
            "AND purpose IS NOT NULL AND btrim(purpose) <> '')",
            name="approved_requires_review_fields",
        ),
        CheckConstraint(
            "status NOT IN ('sent', 'replied', 'meeting_scheduled') OR sent_at IS NOT NULL",
            name="sent_requires_timestamp",
        ),
        CheckConstraint(
            "status NOT IN ('replied', 'meeting_scheduled') OR reply_at IS NOT NULL",
            name="replied_requires_timestamp",
        ),
        CheckConstraint(
            "status <> 'meeting_scheduled' OR meeting_at IS NOT NULL",
            name="meeting_requires_timestamp",
        ),
        CheckConstraint(
            "sent_at IS NULL OR approved_at IS NULL OR sent_at >= approved_at",
            name="sent_after_approval",
        ),
        # Duplicate-send protection across campaigns: one pending message per recipient.
        Index(
            "uq_outreach_one_pending_per_method",
            "contact_method_id",
            unique=True,
            postgresql_where=text(
                "status IN ('drafted', 'approved') AND contact_method_id IS NOT NULL"
            ),
        ),
        Index("ix_outreach_activities_opportunity_id", "opportunity_id"),
        Index("ix_outreach_activities_status", "status"),
        Index("ix_outreach_activities_next_action_at", "next_action_at"),
    )