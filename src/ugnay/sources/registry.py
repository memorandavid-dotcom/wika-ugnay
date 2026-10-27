"""Source registry: config loading, review workflow, and the ingestion guard.

Rules: sources.yaml can only describe a source. Approval and enabling happen
through review_source() and set_enabled(), and every ingestion goes through start_run().
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ugnay.db.constants import (
    COLLECTION_METHODS,
    REVIEW_DECISIONS,
    SOURCE_CATEGORIES,
    WEB_COLLECTION_METHODS,
)
from ugnay.db.models import IngestionRun, Source
from ugnay.db.models_sources import SourceReview

TERMS_REVIEW_MAX_AGE = timedelta(days=365)
STALE_RUN_AGE = timedelta(hours=6)
MAX_ERROR_LENGTH = 500
_DOMAIN = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)


class SourceNotApproved(RuntimeError):
    """The source may not be used (not approved, disabled, stale review, or URL not allowed)."""


class SourceBusy(RuntimeError):
    """A run for this source is already in progress."""


def host_allowed(host: str, domains: list[str]) -> bool:
    host = (host or "").lower().rstrip(".")
    return bool(host) and any(host == d or host.endswith("." + d) for d in domains)


class SourceConfig(BaseModel):
    """What sources.yaml may say. It cannot set enabled, review_status or review fields."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    url: str
    category: str
    connector_type: str = Field(min_length=1, max_length=60)
    collection_method: str
    allowed_domains: list[str] = Field(min_length=1)
    refresh_interval_hours: int = Field(default=168, gt=0)
    requests_per_minute: int = Field(default=10, gt=0, le=60)
    max_response_bytes: int = Field(default=5_000_000, gt=0, le=50_000_000)
    use_notes: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, value: str) -> str:
        value = value.strip()
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("url must be an http(s) URL with a host")
        return value

    @field_validator("category")
    @classmethod
    def _category_known(cls, value: str) -> str:
        if value not in SOURCE_CATEGORIES:
            raise ValueError(f"unknown category {value!r}")
        return value

    @field_validator("collection_method")
    @classmethod
    def _method_known(cls, value: str) -> str:
        if value not in COLLECTION_METHODS:
            raise ValueError(f"unknown collection_method {value!r}")
        return value

    @field_validator("allowed_domains")
    @classmethod
    def _domains_valid(cls, value: list[str]) -> list[str]:
        for domain in value:
            if not _DOMAIN.match(domain):
                raise ValueError(f"not a bare lowercase domain: {domain!r}")
        return value

    @model_validator(mode="after")
    def _host_in_allowlist(self):
        host = urlsplit(self.url).hostname or ""
        if not host_allowed(host, self.allowed_domains):
            raise ValueError("the url's host is not covered by allowed_domains")
        return self


def load_source_configs(path: Path) -> list[SourceConfig]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or set(data) - {"sources"}:
        raise ValueError("sources file must contain only a top-level 'sources' list")
    entries = data.get("sources") or []
    configs = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each source entry must be a mapping")
        configs.append(SourceConfig(**entry))
    names = [c.name for c in configs]
    if len(names) != len(set(names)):
        raise ValueError("duplicate source names in sources file")
    return configs


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    reviews_reset: list[str] = field(default_factory=list)


_SYNCED_FIELDS = (
    "url", "category", "connector_type", "collection_method", "allowed_domains",
    "refresh_interval_hours", "requests_per_minute", "max_response_bytes", "use_notes",
)


def sync_sources(session: Session, configs: list[SourceConfig]) -> SyncResult:
    """New sources start pending and disabled. A material change resets an approved review."""
    result = SyncResult()
    for cfg in configs:
        source = session.execute(
            select(Source).where(Source.name == cfg.name)
        ).scalar_one_or_none()
        if source is None:
            session.add(
                Source(
                    name=cfg.name, url=cfg.url, category=cfg.category,
                    connector_type=cfg.connector_type,
                    collection_method=cfg.collection_method,
                    allowed_domains=list(cfg.allowed_domains),
                    refresh_interval_hours=cfg.refresh_interval_hours,
                    requests_per_minute=cfg.requests_per_minute,
                    max_response_bytes=cfg.max_response_bytes,
                    use_notes=cfg.use_notes,
                    review_status="pending", enabled=False,
                )
            )
            session.flush()
            result.created += 1
            continue

        before_status = source.review_status
        changed = False
        for attr in _SYNCED_FIELDS:
            value = list(cfg.allowed_domains) if attr == "allowed_domains" else getattr(cfg, attr)
            if getattr(source, attr) != value:
                setattr(source, attr, value)
                changed = True
        if not changed:
            result.unchanged += 1
            continue
        session.flush()
        session.refresh(source)  # a database trigger may have reset the review
        result.updated += 1
        if before_status != "pending" and source.review_status == "pending":
            result.reviews_reset.append(source.name)
    return result


def review_source(
    session: Session,
    source: Source,
    *,
    decision: str,
    reviewer: str,
    notes: str,
    terms_url: str | None = None,
    robots_checked: bool = False,
    reviewed_at: datetime | None = None,
) -> SourceReview:
    """Record a review. Approval never enables the source; use set_enabled() for that."""
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"decision must be one of {REVIEW_DECISIONS}")
    reviewer = (reviewer or "").strip()
    notes = (notes or "").strip()
    if not reviewer or not notes:
        raise ValueError("reviewer and notes are required")
    now = reviewed_at or datetime.now(timezone.utc)

    if decision == "approved":
        if not terms_url or not re.match(r"^https?://", terms_url):
            raise ValueError("an approval needs the URL of the terms that were reviewed")
        if source.collection_method in WEB_COLLECTION_METHODS and not robots_checked:
            raise ValueError("web sources need confirmation that robots.txt was checked")
        if not host_allowed(urlsplit(source.url).hostname or "", source.allowed_domains):
            raise ValueError("source url is not covered by its allowed_domains")

    review = SourceReview(
        source_id=source.id, decision=decision, reviewer=reviewer, reviewed_at=now,
        terms_url=terms_url, robots_checked=robots_checked, notes=notes,
    )
    session.add(review)
    source.review_status = decision
    source.reviewed_by = reviewer
    source.review_notes = notes
    source.terms_url = terms_url or source.terms_url
    source.terms_reviewed_at = now
    source.robots_checked_at = now if (decision == "approved" and robots_checked) else None
    source.enabled = False
    session.flush()
    return review


def _check_usable(source: Source, now: datetime | None, require_enabled: bool) -> None:
    now = now or datetime.now(timezone.utc)
    if source.review_status != "approved":
        raise SourceNotApproved(
            f"source {source.name!r} is not approved (status: {source.review_status})"
        )
    if source.terms_reviewed_at is None or now - source.terms_reviewed_at > TERMS_REVIEW_MAX_AGE:
        raise SourceNotApproved(f"source {source.name!r} needs a fresh terms review")
    if not host_allowed(urlsplit(source.url).hostname or "", source.allowed_domains):
        raise SourceNotApproved(f"source {source.name!r} url is outside its allowed domains")
    if require_enabled and not source.enabled:
        raise SourceNotApproved(f"source {source.name!r} is disabled")


def require_ingestable(source: Source, now: datetime | None = None) -> None:
    _check_usable(source, now, require_enabled=True)


def set_enabled(
    session: Session, source: Source, enabled: bool, *, now: datetime | None = None
) -> None:
    if enabled:
        _check_usable(source, now, require_enabled=False)
    source.enabled = enabled
    session.flush()


def assert_url_allowed(source: Source, url: str) -> None:
    """Connectors must call this for every request, including each redirect target."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not host_allowed(
        parts.hostname or "", source.allowed_domains
    ):
        raise SourceNotApproved("URL is outside this source's allowed domains")


def start_run(session: Session, source: Source, *, now: datetime | None = None) -> IngestionRun:
    require_ingestable(source, now)
    running = session.execute(
        select(IngestionRun.id)
        .where(IngestionRun.source_id == source.id, IngestionRun.status == "running")
        .limit(1)
    ).first()
    if running is not None:
        raise SourceBusy(f"source {source.name!r} already has a run in progress")
    run = IngestionRun(source_id=source.id, status="running")
    session.add(run)
    session.flush()
    return run


def _short(error: object) -> str | None:
    if error is None:
        return None
    return str(error)[:MAX_ERROR_LENGTH]  # never pass credentials or page content here


def finish_run(
    session: Session,
    run: IngestionRun,
    *,
    status: str,
    fetched: int = 0,
    new: int = 0,
    updated: int = 0,
    quarantined: int = 0,
    error: object = None,
    now: datetime | None = None,
) -> None:
    if status not in ("succeeded", "partial", "failed"):
        raise ValueError("status must be succeeded, partial or failed")
    if run.status != "running":
        raise ValueError("run is already finished")
    now = now or datetime.now(timezone.utc)
    run.status = status
    run.finished_at = max(now, run.started_at)
    run.records_fetched = fetched
    run.records_new = new
    run.records_updated = updated
    run.records_quarantined = quarantined
    run.error_summary = _short(error)

    source = session.get(Source, run.source_id)
    if status == "succeeded":
        source.last_success_at = now
        source.last_error = None
    else:
        source.last_error = _short(error) or f"run ended with status {status}"
    session.flush()


def fail_stale_runs(
    session: Session, *, older_than: timedelta = STALE_RUN_AGE, now: datetime | None = None
) -> int:
    now = now or datetime.now(timezone.utc)
    stale = session.execute(
        select(IngestionRun).where(
            IngestionRun.status == "running", IngestionRun.started_at < now - older_than
        )
    ).scalars().all()
    for run in stale:
        finish_run(
            session, run, status="failed", now=now,
            error="marked failed: run exceeded the maximum duration (process likely stopped)",
        )
    return len(stale)