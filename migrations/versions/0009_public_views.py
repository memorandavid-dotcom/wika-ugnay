"""public_view schema: explicit-column views and the public reader role

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-21
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

ROLE = "ugnay_public_reader"

VIEWS = {
    "organizations": """
        SELECT o.id, o.name, o.org_type, o.region, o.website_url, o.domain,
               o.date_last_updated
          FROM core.organizations o
         WHERE o.publication_status = 'publishable'
    """,
    "organization_languages": """
        SELECT ol.organization_id, l.iso639_3, l.name AS language_name
          FROM core.organization_languages ol
          JOIN core.organizations o
            ON o.id = ol.organization_id AND o.publication_status = 'publishable'
          JOIN core.languages l ON l.id = ol.language_id
    """,
    "language_resources": """
        SELECT r.id, r.title, r.resource_type, r.description, r.publisher_name,
               o.name AS custodian_name, r.access_url, r.publication_year,
               r.date_last_updated,
               (SELECT rr.license
                  FROM core.resource_rights_reviews rr
                 WHERE rr.resource_id = r.id
                 ORDER BY rr.review_seq DESC
                 LIMIT 1) AS license
          FROM core.language_resources r
          LEFT JOIN core.organizations o
            ON o.id = r.custodian_org_id AND o.publication_status = 'publishable'
         WHERE r.publication_status = 'publishable'
    """,
    "resource_languages": """
        SELECT rl.resource_id, l.iso639_3, l.name AS language_name
          FROM core.resource_languages rl
          JOIN core.language_resources r
            ON r.id = rl.resource_id AND r.publication_status = 'publishable'
          JOIN core.languages l ON l.id = rl.language_id
    """,
    "languages": """
        SELECT l.iso639_3, l.name, l.family
          FROM core.languages l
    """,
    "organization_contact_summary": """
        SELECT o.id AS organization_id,
               CASE WHEN c.n = 0 THEN 'none'
                    WHEN c.n BETWEEN 1 AND 2 THEN '1-2'
                    WHEN c.n BETWEEN 3 AND 5 THEN '3-5'
                    ELSE '6+' END AS professional_contacts_band,
               EXISTS (SELECT 1 FROM core.contact_methods m
                        WHERE m.organization_id = o.id
                          AND m.is_official_inbox
                          AND m.review_status = 'reviewed') AS has_reviewed_official_inbox
          FROM core.organizations o
          LEFT JOIN LATERAL (
                SELECT count(DISTINCT a.contact_id) AS n
                  FROM core.contact_affiliations a
                  JOIN core.contacts ct ON ct.id = a.contact_id
                 WHERE a.organization_id = o.id
                   AND a.is_current
                   AND ct.review_status = 'reviewed'
          ) c ON true
         WHERE o.publication_status = 'publishable'
    """,
}


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute(f"ALTER ROLE {ROLE} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION")
    op.execute(f"ALTER ROLE {ROLE} CONNECTION LIMIT 5")
    op.execute(f"ALTER ROLE {ROLE} SET statement_timeout = '10s'")

    op.execute("CREATE SCHEMA IF NOT EXISTS public_view")
    op.execute("REVOKE ALL ON SCHEMA core FROM PUBLIC")
    for name, body in VIEWS.items():
        op.execute(f"CREATE VIEW public_view.{name} WITH (security_barrier = true) AS {body}")

    op.execute(f"GRANT USAGE ON SCHEMA public_view TO {ROLE}")
    for name in VIEWS:
        op.execute(f"GRANT SELECT ON public_view.{name} TO {ROLE}")


def downgrade() -> None:
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW IF EXISTS public_view.{name}")
    op.execute(f"REVOKE USAGE ON SCHEMA public_view FROM {ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE}")