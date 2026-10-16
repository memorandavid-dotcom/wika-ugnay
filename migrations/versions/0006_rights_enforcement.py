"""enforce rights rules for language resources

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.resource_production_guard() RETURNS trigger AS $$
        DECLARE
            latest RECORD;
        BEGIN
            IF NEW.production_status = 'approved_for_production'
               AND (TG_OP = 'INSERT' OR OLD.production_status IS DISTINCT FROM NEW.production_status) THEN
                SELECT permission_status, permitted_uses, expires_at
                  INTO latest
                  FROM core.resource_rights_reviews
                 WHERE resource_id = NEW.id
                 ORDER BY review_seq DESC
                 LIMIT 1;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'production approval refused: resource has no rights review';
                END IF;
                IF latest.permission_status <> 'approved' THEN
                    RAISE EXCEPTION 'production approval refused: latest rights review is not approved';
                END IF;
                IF NOT ('product_use' = ANY (latest.permitted_uses)) THEN
                    RAISE EXCEPTION 'production approval refused: latest review does not permit product_use';
                END IF;
                IF latest.expires_at IS NOT NULL AND latest.expires_at <= now() THEN
                    RAISE EXCEPTION 'production approval refused: latest rights review has expired';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER resource_production_guard_trg
        BEFORE INSERT OR UPDATE ON core.language_resources
        FOR EACH ROW EXECUTE FUNCTION core.resource_production_guard()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.rights_review_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'resource_rights_reviews is append-only; add a new review instead';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER rights_review_append_only_trg
        BEFORE UPDATE OR DELETE ON core.resource_rights_reviews
        FOR EACH ROW EXECUTE FUNCTION core.rights_review_append_only()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.rights_review_revoke() RETURNS trigger AS $$
        BEGIN
            IF NEW.permission_status <> 'approved'
               OR NOT ('product_use' = ANY (NEW.permitted_uses))
               OR (NEW.expires_at IS NOT NULL AND NEW.expires_at <= now()) THEN
                UPDATE core.language_resources
                   SET production_status = 'revoked'
                 WHERE id = NEW.resource_id
                   AND production_status = 'approved_for_production';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER rights_review_revoke_trg
        AFTER INSERT ON core.resource_rights_reviews
        FOR EACH ROW EXECUTE FUNCTION core.rights_review_revoke()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS rights_review_revoke_trg ON core.resource_rights_reviews")
    op.execute("DROP FUNCTION IF EXISTS core.rights_review_revoke()")
    op.execute("DROP TRIGGER IF EXISTS rights_review_append_only_trg ON core.resource_rights_reviews")
    op.execute("DROP FUNCTION IF EXISTS core.rights_review_append_only()")
    op.execute("DROP TRIGGER IF EXISTS resource_production_guard_trg ON core.language_resources")
    op.execute("DROP FUNCTION IF EXISTS core.resource_production_guard()")