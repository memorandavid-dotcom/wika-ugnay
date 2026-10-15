import hashlib
import itertools

import pytest
from sqlalchemy.orm import Session

from ugnay.db.models import Organization, Source, SourceObservation
from ugnay.db.session import get_engine


@pytest.fixture
def session():
    connection = get_engine().connect()
    outer = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield db
    finally:
        db.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def source(session):
    row = Source(
        name="Fixture Source",
        url="https://example.gov.ph/directory",
        category="government_directory",
        connector_type="html_directory",
        collection_method="html_public_page",
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def new_observation(session, source):
    counter = itertools.count()

    def _make(entity_type="contact", payload=None):
        n = next(counter)
        obs = SourceObservation(
            source_id=source.id,
            entity_type=entity_type,
            source_url=f"https://example.gov.ph/page{n}",
            raw_payload=payload or {"n": n},
            content_hash=hashlib.sha256(str(n).encode()).hexdigest(),
        )
        session.add(obs)
        session.flush()
        return obs

    return _make


@pytest.fixture
def org(session):
    row = Organization(name="Fixture Org", normalized_name="fixture org", org_type="university")
    session.add(row)
    session.flush()
    return row