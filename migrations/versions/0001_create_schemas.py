"""create core and public_view schemas

Revision ID: 0001_create_schemas
Revises:
Create Date: 2026-10-15
"""
from alembic import op

revision = "0001_create_schemas"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS public_view")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS public_view")
    op.execute("DROP SCHEMA IF EXISTS core")