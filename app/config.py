"""
Configuration management for obsidian2confluence.

This module loads environment variables (optionally via a .env file) and validates them
using pydantic models. The resulting Settings object is used throughout the app.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, EmailStr, Field, HttpUrl, ValidationError, field_validator


class Settings(BaseModel):
    """Runtime configuration derived from environment variables."""

    confluence_base_url: HttpUrl = Field(alias="CONFLUENCE_BASE_URL")
    confluence_email: EmailStr = Field(alias="CONFLUENCE_EMAIL")
    confluence_api_token: str = Field(alias="CONFLUENCE_API_TOKEN", min_length=1)
    confluence_space_key: str = Field(alias="CONFLUENCE_SPACE_KEY", min_length=1)
    confluence_root_page_title: str = Field(
        alias="CONFLUENCE_ROOT_PAGE_TITLE", default="Knowledge Base", min_length=1
    )
    obsidian_vault_path: Path = Field(alias="OBSIDIAN_VAULT_PATH")
    sync_interval_minutes: int = Field(alias="SYNC_INTERVAL_MINUTES", default=60, ge=1)
    log_level: str = Field(alias="LOG_LEVEL", default="INFO")
    dry_run: bool = Field(alias="DRY_RUN", default=False)

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }

    @field_validator("log_level", mode="after")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {', '.join(sorted(allowed))}")
        return normalized

    @field_validator("dry_run", mode="before")
    @classmethod
    def parse_bool(cls, value: str | bool) -> bool:
        if isinstance(value, bool):
            return value
        truthy = {"1", "true", "t", "yes", "y", "on"}
        falsy = {"0", "false", "f", "no", "n", "off"}
        lower = value.strip().lower()
        if lower in truthy:
            return True
        if lower in falsy:
            return False
        raise ValueError("DRY_RUN must be a boolean-like value (true/false)")

    @field_validator("obsidian_vault_path", mode="after")
    @classmethod
    def ensure_absolute_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else value.resolve()


def _find_env_file(explicit_path: Optional[Path] = None) -> Optional[Path]:
    """Detect the .env file to load if present."""
    if explicit_path:
        if explicit_path.exists():
            return explicit_path
        raise FileNotFoundError(f"Explicit .env file not found: {explicit_path}")
    default_path = Path(".env")
    return default_path if default_path.exists() else None


def load_settings(env_file: Optional[Path] = None) -> Settings:
    """
    Load and validate configuration from environment variables.

    Parameters
    ----------
    env_file:
        Path to a .env file. If omitted, `.env` in the working directory is used when present.

    Returns
    -------
    Settings
        Validated configuration object.

    Raises
    ------
    ValidationError
        If the configuration is invalid or incomplete.
    """
    env_path = _find_env_file(env_file)
    if env_path:
        load_dotenv(env_path, override=False)

    try:
        settings = Settings.model_validate(os.environ)
    except ValidationError as exc:  # pragma: no cover - re-raise with context
        missing = {err["loc"][0] for err in exc.errors() if err["type"] == "missing"}
        hint = ""
        if missing:
            missing_env = ", ".join(sorted(missing))
            hint = f" Missing environment variables: {missing_env}."
        raise ValidationError(
            exc.errors(), exc.model  # type: ignore[arg-type]
        ) from RuntimeError(f"Invalid configuration.{hint}")

    if not settings.obsidian_vault_path.exists():
        raise FileNotFoundError(
            f"OBSIDIAN_VAULT_PATH does not exist: {settings.obsidian_vault_path}"
        )

    return settings

