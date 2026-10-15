"""protect suppression_list from deletion and tampering

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.suppression_protect() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'suppression_list rows cannot be deleted; lift the entry instead';
            END IF;
            IF OLD.status = 'lifted' THEN
                RAISE EXCEPTION 'lifted suppression entries are immutable audit records';
            END IF;
            IF NEW.value_type <> OLD.value_type
               OR NEW.normalized_value <> OLD.normalized_value THEN
                RAISE EXCEPTION 'suppressed value cannot be changed; add a new entry instead';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER suppression_protect_trg
        BEFORE UPDATE OR DELETE ON core.suppression_list
        FOR EACH ROW EXECUTE FUNCTION core.suppression_protect()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS suppression_protect_trg ON core.suppression_list")
    op.execute("DROP FUNCTION IF EXISTS core.suppression_protect()")