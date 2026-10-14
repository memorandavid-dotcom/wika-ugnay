import pytest
from sqlalchemy.orm import Session

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