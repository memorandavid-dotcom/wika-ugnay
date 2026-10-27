"""SQLAlchemy models, part E: source review audit trail."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ugnay.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, in_list_check
from ugnay.db.constants import REVIEW_DECISIONS


class SourceReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only record of every review decision. A trigger blocks UPDATE and DELETE (0011)."""

    __tablename__ = "source_reviews"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.sources.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(100), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terms_url: Mapped[str | None] = mapped_column(Text)
    robots_checked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        in_list_check("decision", REVIEW_DECISIONS, "decision_valid"),
        CheckConstraint("btrim(reviewer) <> ''", name="reviewer_not_blank"),
        CheckConstraint("btrim(notes) <> ''", name="notes_not_blank"),
        CheckConstraint(
            "decision <> 'approved' OR (terms_url IS NOT NULL AND terms_url ~ '^https?://')",
            name="approval_requires_terms_url",
        ),
        Index("ix_source_reviews_source_reviewed", "source_id", "reviewed_at"),
    )