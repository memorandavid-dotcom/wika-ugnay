from sqlalchemy import select

from ugnay.db.models import Language
from ugnay.jobs.seed_languages import LanguageRow, upsert_languages


def test_upsert_is_idempotent(session):
    rows = [
        LanguageRow("qaa", "Test One", "Test Family", "test1234"),
        LanguageRow("qab", "Test Two", None, "test5678"),
    ]
    assert upsert_languages(session, rows, "test") == (2, 0)
    assert upsert_languages(session, rows, "test") == (0, 2)
    count = session.scalars(select(Language).where(Language.iso639_3.in_(["qaa", "qab"]))).all()
    assert len(count) == 2


def test_upsert_refreshes_name_and_notes(session):
    upsert_languages(session, [LanguageRow("qaa", "Old Name", None, "test1234")], "v1")
    upsert_languages(session, [LanguageRow("qaa", "New Name", None, "test1234")], "v2")
    language = session.scalars(select(Language).where(Language.iso639_3 == "qaa")).one()
    session.refresh(language)
    assert language.name == "New Name"
    assert "v2" in language.notes