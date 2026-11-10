from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to this file rather than ".env" so discovery doesn't depend on the
# process's working directory (e.g. `cd backend && pytest`).
_ROOT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """Phase 0 settings only.

    Fields for later phases (JWT signing, Groq, email provider, grace-token
    encryption) are intentionally not declared here yet -- see .env.example
    for the full forward-looking list of variables those phases will need.
    """

    model_config = SettingsConfigDict(env_file=_ROOT_ENV_FILE, extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    # No default: a missing DATABASE_URL must fail loudly at startup rather
    # than silently falling back to credentials that don't match .env.example
    # / docker-compose.yml.
    database_url: str

    cors_allowed_origins: str = "http://localhost:5173"

    api_v1_prefix: str = "/api/v1"

    @property
    def sync_database_url(self) -> str:
        """Alembic runs migrations synchronously; swap the async driver for
        a sync one rather than maintaining two separate URLs by hand."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
