"""source review rules, audit-log protection, and the ingestion guard

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-26
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE core.sources ADD CONSTRAINT ck_sources_allowed_domains_lowercase
        CHECK (array_to_string(allowed_domains, ',') = lower(array_to_string(allowed_domains, ',')))
        """
    )
    op.execute(
        """
        ALTER TABLE core.sources ADD CONSTRAINT ck_sources_approved_requires_evidence
        CHECK (review_status <> 'approved' OR (terms_reviewed_at IS NOT NULL
               AND reviewed_by IS NOT NULL AND btrim(reviewed_by) <> ''
               AND terms_url IS NOT NULL AND terms_url ~ '^https?://'
               AND review_notes IS NOT NULL AND btrim(review_notes) <> ''
               AND cardinality(allowed_domains) >= 1))
        """
    )
    op.execute(
        """
        ALTER TABLE core.sources ADD CONSTRAINT ck_sources_web_approval_requires_robots_check
        CHECK (review_status <> 'approved'
               OR collection_method NOT IN ('html_public_page', 'sitemap')
               OR robots_checked_at IS NOT NULL)
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.source_reviews_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'source_reviews is append-only; add a new review instead';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER source_reviews_append_only_trg
        BEFORE UPDATE OR DELETE ON core.source_reviews
        FOR EACH ROW EXECUTE FUNCTION core.source_reviews_append_only()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.source_material_change_reset() RETURNS trigger AS $$
        BEGIN
            IF OLD.review_status <> 'pending'
               AND NEW.review_status = OLD.review_status
               AND (NEW.url IS DISTINCT FROM OLD.url
                    OR NEW.category IS DISTINCT FROM OLD.category
                    OR NEW.connector_type IS DISTINCT FROM OLD.connector_type
                    OR NEW.collection_method IS DISTINCT FROM OLD.collection_method
                    OR NEW.allowed_domains IS DISTINCT FROM OLD.allowed_domains) THEN
                NEW.review_status := 'pending';
                NEW.enabled := false;
                NEW.terms_reviewed_at := NULL;
                NEW.reviewed_by := NULL;
                NEW.review_notes := NULL;
                NEW.robots_checked_at := NULL;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER source_material_change_reset_trg
        BEFORE UPDATE ON core.sources
        FOR EACH ROW EXECUTE FUNCTION core.source_material_change_reset()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.ingestion_run_guard() RETURNS trigger AS $$
        DECLARE
            src RECORD;
        BEGIN
            SELECT enabled, review_status INTO src FROM core.sources WHERE id = NEW.source_id;
            IF NOT FOUND OR NOT src.enabled OR src.review_status <> 'approved' THEN
                RAISE EXCEPTION 'ingestion refused: source is not approved and enabled';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER ingestion_run_guard_trg
        BEFORE INSERT ON core.ingestion_runs
        FOR EACH ROW EXECUTE FUNCTION core.ingestion_run_guard()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ingestion_run_guard_trg ON core.ingestion_runs")
    op.execute("DROP FUNCTION IF EXISTS core.ingestion_run_guard()")
    op.execute("DROP TRIGGER IF EXISTS source_material_change_reset_trg ON core.sources")
    op.execute("DROP FUNCTION IF EXISTS core.source_material_change_reset()")
    op.execute("DROP TRIGGER IF EXISTS source_reviews_append_only_trg ON core.source_reviews")
    op.execute("DROP FUNCTION IF EXISTS core.source_reviews_append_only()")
    op.execute(
        "ALTER TABLE core.sources DROP CONSTRAINT IF EXISTS ck_sources_web_approval_requires_robots_check"
    )
    op.execute(
        "ALTER TABLE core.sources DROP CONSTRAINT IF EXISTS ck_sources_approved_requires_evidence"
    )
    op.execute(
        "ALTER TABLE core.sources DROP CONSTRAINT IF EXISTS ck_sources_allowed_domains_lowercase"
    )