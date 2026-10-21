"""enforce evidence, status flow and suppression for outreach

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

QUALIFIED = (
    "'qualified', 'approved_for_outreach', 'engaged', "
    "'meeting_scheduled', 'partnership_established'"
)


def upgrade() -> None:
    # --- suppression lookup usable from triggers (mirrors outreach/suppression.py) ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.is_suppressed_sql(p_type text, p_value text)
        RETURNS boolean AS $$
        DECLARE
            host text;
            cand text;
        BEGIN
            IF p_type = 'email' THEN
                IF EXISTS (SELECT 1 FROM core.suppression_list
                            WHERE status = 'active' AND value_type = 'email'
                              AND normalized_value = p_value) THEN
                    RETURN true;
                END IF;
                host := split_part(p_value, '@', 2);
            ELSIF p_type = 'phone' THEN
                RETURN EXISTS (SELECT 1 FROM core.suppression_list
                                WHERE status = 'active' AND value_type = 'phone'
                                  AND normalized_value = p_value);
            ELSIF p_type = 'contact_form' THEN
                host := lower(substring(p_value FROM '^https?://([^/?#:]+)'));
            ELSE
                RAISE EXCEPTION 'unsupported contact method type for suppression check';
            END IF;

            IF host IS NULL OR host = '' THEN
                RAISE EXCEPTION 'cannot determine host for suppression check';
            END IF;

            cand := host;
            IF position('.' IN cand) = 0 THEN
                RETURN EXISTS (SELECT 1 FROM core.suppression_list
                                WHERE status = 'active' AND value_type = 'domain'
                                  AND normalized_value = cand);
            END IF;
            WHILE position('.' IN cand) > 0 LOOP
                IF EXISTS (SELECT 1 FROM core.suppression_list
                            WHERE status = 'active' AND value_type = 'domain'
                              AND normalized_value = cand) THEN
                    RETURN true;
                END IF;
                cand := substring(cand FROM position('.' IN cand) + 1);
            END LOOP;
            RETURN false;
        END;
        $$ LANGUAGE plpgsql STABLE
        """
    )

    # --- qualified opportunities need evidence ---
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION core.opportunity_evidence_guard() RETURNS trigger AS $$
        BEGIN
            IF NEW.stage IN ({QUALIFIED})
               AND (TG_OP = 'INSERT' OR OLD.stage IS DISTINCT FROM NEW.stage) THEN
                IF NOT EXISTS (SELECT 1 FROM core.opportunity_evidence
                                WHERE opportunity_id = NEW.id) THEN
                    RAISE EXCEPTION 'qualification refused: opportunity has no source evidence';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER opportunity_evidence_guard_trg
        BEFORE INSERT OR UPDATE ON core.partnership_opportunities
        FOR EACH ROW EXECUTE FUNCTION core.opportunity_evidence_guard()
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION core.evidence_delete_guard() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM core.partnership_opportunities
                        WHERE id = OLD.opportunity_id AND stage IN ({QUALIFIED}))
               AND NOT EXISTS (SELECT 1 FROM core.opportunity_evidence
                                WHERE opportunity_id = OLD.opportunity_id
                                  AND source_observation_id <> OLD.source_observation_id) THEN
                RAISE EXCEPTION 'cannot remove the last evidence of a qualified opportunity';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER evidence_delete_guard_trg
        BEFORE DELETE ON core.opportunity_evidence
        FOR EACH ROW EXECUTE FUNCTION core.evidence_delete_guard()
        """
    )

    # --- outreach status flow, locked content, suppression, real-send checks ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.outreach_guard() RETURNS trigger AS $$
        DECLARE
            camp RECORD;
            m RECORD;
            opp_stage text;
            contact_review text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status NOT IN ('drafted', 'blocked') THEN
                    RAISE EXCEPTION 'new outreach activities must start as drafted or blocked';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.status <> 'drafted'
               AND (NEW.draft_body IS DISTINCT FROM OLD.draft_body
                    OR NEW.subject IS DISTINCT FROM OLD.subject)
               AND NOT (NEW.draft_body = '[erased]'
                        AND (NEW.subject IS NULL OR NEW.subject = '[erased]')) THEN
                RAISE EXCEPTION 'message content is locked after approval; cancel and draft a new message';
            END IF;

            IF NEW.status IS DISTINCT FROM OLD.status THEN
                IF NOT (
                    (OLD.status = 'drafted' AND NEW.status IN ('approved', 'cancelled', 'blocked'))
                    OR (OLD.status = 'approved' AND NEW.status IN ('sent', 'cancelled', 'blocked'))
                    OR (OLD.status = 'sent' AND NEW.status IN ('replied', 'closed'))
                    OR (OLD.status = 'replied' AND NEW.status IN ('meeting_scheduled', 'closed'))
                    OR (OLD.status = 'meeting_scheduled' AND NEW.status = 'closed')
                ) THEN
                    RAISE EXCEPTION 'invalid outreach status transition';
                END IF;

                IF NEW.status IN ('approved', 'sent') THEN
                    IF NEW.contact_method_id IS NULL THEN
                        RAISE EXCEPTION 'outreach refused: no recipient contact method';
                    END IF;
                    SELECT method_type, normalized_value, review_status, contact_id
                      INTO m FROM core.contact_methods WHERE id = NEW.contact_method_id;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'outreach refused: contact method not found';
                    END IF;
                    IF core.is_suppressed_sql(m.method_type, m.normalized_value) THEN
                        RAISE EXCEPTION 'outreach refused: recipient is on the suppression list';
                    END IF;
                END IF;

                IF NEW.status = 'sent' AND NOT NEW.is_dry_run THEN
                    SELECT dry_run, status INTO camp
                      FROM core.campaigns WHERE id = NEW.campaign_id;
                    IF camp.dry_run OR camp.status <> 'active' THEN
                        RAISE EXCEPTION 'real send refused: campaign is not live and active';
                    END IF;
                    SELECT stage INTO opp_stage
                      FROM core.partnership_opportunities WHERE id = NEW.opportunity_id;
                    IF opp_stage IS NULL OR opp_stage NOT IN ('approved_for_outreach', 'engaged') THEN
                        RAISE EXCEPTION 'real send refused: opportunity is not approved for outreach';
                    END IF;
                    IF m.review_status <> 'reviewed' THEN
                        RAISE EXCEPTION 'real send refused: contact method has not been reviewed';
                    END IF;
                    IF m.contact_id IS NOT NULL THEN
                        SELECT review_status INTO contact_review
                          FROM core.contacts WHERE id = m.contact_id;
                        IF contact_review IS DISTINCT FROM 'reviewed' THEN
                            RAISE EXCEPTION 'real send refused: named contact has not been reviewed';
                        END IF;
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER outreach_guard_trg
        BEFORE INSERT OR UPDATE ON core.outreach_activities
        FOR EACH ROW EXECUTE FUNCTION core.outreach_guard()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS outreach_guard_trg ON core.outreach_activities")
    op.execute("DROP FUNCTION IF EXISTS core.outreach_guard()")
    op.execute("DROP TRIGGER IF EXISTS evidence_delete_guard_trg ON core.opportunity_evidence")
    op.execute("DROP FUNCTION IF EXISTS core.evidence_delete_guard()")
    op.execute(
        "DROP TRIGGER IF EXISTS opportunity_evidence_guard_trg ON core.partnership_opportunities"
    )
    op.execute("DROP FUNCTION IF EXISTS core.opportunity_evidence_guard()")
    op.execute("DROP FUNCTION IF EXISTS core.is_suppressed_sql(text, text)")