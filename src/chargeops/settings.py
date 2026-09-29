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

    # Where the assistant finds the MCP server. Same value the client passes
    # to `claude mcp add`.
    mcp_url: str = "http://127.0.0.1:8765/mcp"

    # The assistant needs a model. The SERVER does not — it only runs SQL.
    openai_api_key: str = ""
    openai_model: str = "gpt-5-nano"

    # Signs the short-lived browser tokens. A DIFFERENT secret from
    # api_token: that one is a bearer credential, this one is a signing key,
    # and reusing a secret across two purposes is how one leak becomes two.
    jwt_secret: str = ""
    browser_token_minutes: int = 15


settings = Settings()
