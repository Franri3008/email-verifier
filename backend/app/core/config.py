from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    app_name: str = "Email Checker"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./email_checker.db"
    encryption_key: str = ""
    public_url: str = "http://localhost:3000"
    secure_cookies: bool = False
    production: bool = False
    session_hours: int = 24
    retention_hours: int = 24
    max_upload_bytes: int = 5 * 1024 * 1024
    max_active_jobs: int = 2
    max_jobs_per_hour: int = 30
    job_timeout_seconds: int = 1800
    static_dir: str = ""
    run_worker: bool = True
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost:3000"
    openrouter_app_name: str = "Email Checker"

    verifalia_username: str | None = None
    verifalia_password: str | None = None
    verifalia_bearer_token: str | None = None
    verifalia_base_url: str = "https://api.verifalia.com/v2.7"

    request_timeout_seconds: float = 45.0
    verification_timeout_seconds: float = 240.0
    max_batch_rows: int = Field(default=1_000, ge=1, le=25_000)
    verifalia_chunk_size: int = Field(default=500, ge=1, le=10_000)
    batch_result_ttl_seconds: int = Field(default=3_600, ge=60)

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        origins = [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        ]
        local_pair = {"http://localhost:3000", "http://127.0.0.1:3000"}
        if local_pair.intersection(origins):
            origins.extend(origin for origin in local_pair if origin not in origins)
        return origins

    @property
    def has_verifalia_credentials(self) -> bool:
        return bool(
            self.verifalia_bearer_token
            or (self.verifalia_username and self.verifalia_password)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
