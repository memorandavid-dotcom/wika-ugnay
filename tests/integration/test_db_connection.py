from sqlalchemy import text

from ugnay.db.session import get_engine


def test_can_connect():
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1


def test_schemas_exist_after_migration():
    query = text(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name IN ('core', 'public_view')"
    )
    with get_engine().connect() as conn:
        found = set(conn.execute(query).scalars().all())
    assert found == {"core", "public_view"}