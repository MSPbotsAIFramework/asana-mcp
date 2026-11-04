from pydantic_settings import BaseSettings, SettingsConfigDict

# Credential header name. Declared here (not just in README) so server.py and
# tests reference the same literal -- this is the one name that must stay in
# lockstep with the README's Authentication headers table.
ASANA_TOKEN_HEADER = "X-Asana-Access-Token"


class Settings(BaseSettings):
    """Non-credential configuration. Must tolerate unknown env vars (extra="ignore")
    because the runtime injects variables this project never declared.

    No credential field exists here on purpose: per-request credentials come
    only from the Header (see server.py), never from the environment.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"

    # Asana REST API v1.0 base URL. Not expected to vary per tenant (Asana has
    # no self-hosted/region variant), kept configurable only for testing.
    asana_api_root: str = "https://app.asana.com/api/1.0"


def get_settings() -> Settings:
    return Settings()
