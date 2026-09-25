"""Typed configuration, read once at import. Fails at startup, not mid-query."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_prefix=""
    )

    # Read-only login. NEVER ops_owner — every guard depends on this.
    database_url: str = (
        "postgresql://ops_reader:reader_dev_password@localhost:5434/chargeops"
    )
    # Cap on rows returned to a model. 9,000 sessions must never all come back.
    max_rows: int = 200

    # HTTP transport. 127.0.0.1 means localhost only — binding 0.0.0.0
    # exposes the database to your whole network.
    host: str = "127.0.0.1"
    port: int = 8765

    # Shared secret clients must present. Empty = no auth (see server.py).
    api_token: str = ""


settings = Settings()
