"""Application configuration via environment variables."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    The default environment is ``production`` so that a deployment that forgets to
    configure anything fails closed. Local development opts in with
    ``SHELFMARK_ENV=development``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    log_level: str = "INFO"
    log_format: str = "json"
    host: str = "0.0.0.0"
    port: int = 8000

    env: Literal["development", "production"] = Field(
        "production", validation_alias="SHELFMARK_ENV"
    )
    # Amp sets AMP_DEPLOYMENT_DATA_DIRECTORY on a Box; it survives redeploys.
    data_dir: Path = Field(
        Path("."),
        validation_alias=AliasChoices(
            "SHELFMARK_DATA_DIR", "AMP_DEPLOYMENT_DATA_DIRECTORY"
        ),
    )
    database_url_override: str | None = Field(None, validation_alias="DATABASE_URL")

    # Identity: "auth0" (Sign in with Auth0) or "local" (single local user, dev only).
    auth_provider: Literal["auth0", "local"] = Field(
        "auth0", validation_alias="SHELFMARK_AUTH"
    )
    allowed_user_ids: str = Field(
        "",
        validation_alias=AliasChoices(
            "SHELFMARK_ALLOWED_USER_IDS", "APP_ALLOWED_USER_IDS"
        ),
    )
    auth0_domain: str = Field("", validation_alias="AUTH0_DOMAIN")
    auth0_client_id: str = Field("", validation_alias="AUTH0_CLIENT_ID")
    auth0_client_secret: str = Field("", validation_alias="AUTH0_CLIENT_SECRET")
    auth0_redirect_uri: str = Field("", validation_alias="AUTH0_REDIRECT_URI")
    deployment_url: str = Field("", validation_alias="AMP_DEPLOYMENT_URL")
    session_secret: str = Field("", validation_alias="APP_SESSION_SECRET")

    refresh_minutes: int = Field(20, validation_alias="SHELFMARK_REFRESH_MINUTES")

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return f"sqlite+aiosqlite:///{(self.data_dir / 'shelfmark.sqlite3').resolve()}"

    @property
    def allowed_user_id_set(self) -> frozenset[str]:
        return frozenset(
            part.strip() for part in self.allowed_user_ids.split(",") if part.strip()
        )
