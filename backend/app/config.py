from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database — Railway provides this; swap postgresql:// → postgresql+asyncpg://
    database_url: str = "sqlite+aiosqlite:///./centras_tokenizer.db"

    # Auth
    jwt_secret_key: str = "CHANGE_ME_TO_A_SECURE_RANDOM_32_CHAR_SECRET"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # Admin credentials (single-user internal tool)
    admin_username: str = "admin"
    admin_password: str = "centras_admin_2024"

    # CORS — comma-separated list of origins
    cors_origins_raw: str = "http://localhost:5173,http://localhost:3000"

    # Runtime
    environment: str = "development"
    log_level: str = "INFO"
    rate_limit_per_minute: int = 30

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_db_url(cls, v: Any) -> str:
        """
        Railway PostgreSQL plugin provides DATABASE_URL with postgresql:// scheme.
        asyncpg requires postgresql+asyncpg:// — normalize transparently.
        """
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if isinstance(v, str) and v.startswith("postgres://"):
            # Some Railway versions emit postgres://
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if not self.is_production:
            return self

        if self.jwt_secret_key.startswith("CHANGE_ME") or len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must be set to a strong 32+ character secret in production")

        weak_passwords = {
            "centras_admin_2024",
            "change-me-strong-password",
            "CHANGE_ME",
        }
        if self.admin_password in weak_passwords or len(self.admin_password) < 12:
            raise ValueError("ADMIN_PASSWORD must be changed to a strong 12+ character password in production")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
