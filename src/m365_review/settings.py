"""Application configuration, loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Placeholder secrets that mean "not really configured" — trigger auto-generation.
_PLACEHOLDER_SECRETS = {
    "",
    "change-me-to-a-long-random-string",
    "dev-insecure-secret-change-me",
}

# Repo root = three parents up from this file (src/m365_review/settings.py -> repo root).
# NOTE: this only holds for an editable/source checkout. When the package is
# pip-installed (e.g. in the Docker image), it lives in site-packages and this
# path is wrong — so config/output dirs must resolve to a location that actually
# exists at runtime. In the container CONFIG_DIR/OUTPUT_DIR are set explicitly.
REPO_ROOT = Path(__file__).resolve().parents[2]


def _first_existing(*candidates: Path, fallback: Path) -> Path:
    for c in candidates:
        if c.exists():
            return c
    return fallback


def _default_config_dir() -> Path:
    """Prefer a source-checkout ./config, else the CWD's ./config (container)."""
    cwd_config = Path.cwd() / "config"
    return _first_existing(REPO_ROOT / "config", cwd_config, fallback=cwd_config)


def _default_data_dir() -> Path:
    """Where the SQLite profiles DB lives. Source-checkout ./data, else CWD ./data."""
    cwd_data = Path.cwd() / "data"
    return _first_existing(REPO_ROOT / "data", cwd_data, fallback=cwd_data)


DEFAULT_CONFIG_DIR = _default_config_dir()
DEFAULT_DATA_DIR = _default_data_dir()


class Settings(BaseSettings):
    """Runtime settings. All secrets come from the environment, never hard-coded."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Azure AD app registration (the MSP's single multi-tenant app) ---
    azure_app_client_id: str = Field(
        default="",
        alias="AZURE_APP_CLIENT_ID",
        description="Application (client) ID of the MSP's multi-tenant app registration.",
    )
    azure_authority: str = Field(
        default="https://login.microsoftonline.com/organizations",
        alias="AZURE_AUTHORITY",
    )
    azure_redirect_uri: str = Field(
        default="http://localhost:8000/auth/callback",
        alias="AZURE_REDIRECT_URI",
    )

    # --- Web session ---
    session_secret: str = Field(
        default="dev-insecure-secret-change-me",
        alias="SESSION_SECRET",
        description="Secret used to sign the browser session cookie.",
    )

    # --- Paths ---
    output_dir: Path = Field(default=REPO_ROOT / "reports", alias="OUTPUT_DIR")
    config_dir: Path = Field(default=DEFAULT_CONFIG_DIR, alias="CONFIG_DIR")
    data_dir: Path = Field(default=DEFAULT_DATA_DIR, alias="DATA_DIR")

    # --- Pricing ---
    # Optional URL to an online rate card (JSON dict {skuPartNumber: price},
    # a JSON list of {sku, price}, or CSV with sku/price columns). When set, it
    # overrides/extends config/sku_prices.yaml; a cached copy is used if offline.
    price_source_url: str = Field(default="", alias="PRICE_SOURCE_URL")

    # --- Reporting / branding ---
    report_company_name: str = Field(default="", alias="REPORT_COMPANY_NAME")

    # --- Web server bind ---
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    # --- Graph scopes: READ-ONLY ONLY. Never add a write scope. ---
    graph_scopes: tuple[str, ...] = (
        "User.Read",
        "Directory.Read.All",
        "User.Read.All",
        "Organization.Read.All",
        "AuditLog.Read.All",
        "Reports.Read.All",
        "Policy.Read.All",
    )

    @property
    def sku_prices_path(self) -> Path:
        return self.config_dir / "sku_prices.yaml"

    @property
    def sku_display_names_path(self) -> Path:
        return self.config_dir / "sku_display_names.yaml"

    @property
    def sku_overlaps_path(self) -> Path:
        return self.config_dir / "sku_overlaps.yaml"

    @property
    def db_path(self) -> Path:
        """SQLite database file holding saved connection profiles."""
        return self.data_dir / "m365_review.db"

    @property
    def price_cache_path(self) -> Path:
        """Cached copy of the online rate card (used when offline)."""
        return self.data_dir / "prices_cache.json"


def _resolve_session_secret(settings: "Settings") -> str:
    """Return a stable session secret without requiring manual .env setup.

    Priority: an explicitly-set SESSION_SECRET wins. Otherwise read (or create)
    a random secret persisted at ``<data_dir>/.session_secret`` so browser
    sessions survive container restarts. Falls back to an ephemeral in-memory
    secret only if the data dir isn't writable.
    """
    if settings.session_secret not in _PLACEHOLDER_SECRETS:
        return settings.session_secret

    secret_file = settings.data_dir / ".session_secret"
    try:
        if secret_file.exists():
            existing = secret_file.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_urlsafe(48)
        secret_file.write_text(generated, encoding="utf-8")
        try:
            os.chmod(secret_file, 0o600)
        except OSError:
            pass
        logger.info("Generated a new persistent session secret at %s", secret_file)
        return generated
    except OSError:
        logger.warning("Could not persist a session secret; using an ephemeral one for this run.")
        return secrets.token_urlsafe(48)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton (with a resolved session secret)."""
    settings = Settings()
    settings.session_secret = _resolve_session_secret(settings)
    return settings
