from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "troque-em-producao"


def normalize_database_url(url: str) -> str:
    """Aceita URLs no formato dos provedores (postgres://, postgresql://) e
    converte para o driver psycopg 3 usado pelo SQLAlchemy."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://agendamento:agendamento@localhost:5432/agendamento"
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_expire_minutes: int = 60 * 12

    @field_validator("database_url")
    @classmethod
    def _normalize_url(cls, value: str) -> str:
        return normalize_database_url(value)

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        if self.env == "production" and (
            self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError("Em producao, JWT_SECRET precisa ter ao menos 32 caracteres")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
