from ugnay.config import Settings


def test_database_url_handles_special_characters():
    settings = Settings(
        _env_file=None,
        postgres_user="u",
        postgres_password="p@ss:word/1",
        postgres_db="d",
    )
    url = settings.database_url
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "p@ss:word/1"
    assert "p@ss" not in repr(url)  # password is masked when printed