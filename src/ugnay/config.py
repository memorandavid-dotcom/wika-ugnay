from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

PUBLIC_READER_ROLE = "ugnay_public_reader"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    log_level: str = "INFO"
    public_reader_password: SecretStr | None = None

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def public_database_url(self) -> URL:
        if self.public_reader_password is None:
            raise ValueError("PUBLIC_READER_PASSWORD is not set in .env")
        return URL.create(
            drivername="postgresql+psycopg",
            username=PUBLIC_READER_ROLE,
            password=self.public_reader_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()