from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration comes from the environment.

    This is the twelve-factor rule and it is what makes the same image
    runnable in dev, staging and prod without a rebuild.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Finance Dashboard API"
    environment: str = "development"
    log_level: str = "INFO"

    # Hostnames here ("db", "cache") are Compose service names, which Docker's
    # embedded DNS resolves on the user-defined bridge network.
    database_url: str = "postgresql+psycopg://finance:finance@db:5432/finance"
    redis_url: str = "redis://cache:6379/0"

    cors_origins: str = "http://localhost:5173"

    # Market data. Provider "demo" generates deterministic synthetic prices so
    # the stack runs with zero external accounts. The default stays "demo" on
    # purpose: a fresh clone must work offline and must not make surprise
    # outbound calls. .env.example selects "openbb".
    #   demo    -- synthetic, offline, no key
    #   openbb  -- OpenBB Platform (see market_openbb_provider)
    #   finnhub -- Finnhub directly, needs market_api_key
    market_provider: str = "demo"
    market_api_key: str = ""

    # Which upstream source OpenBB should use. yfinance needs no API key;
    # fmp/intrinio/polygon do (configured in OpenBB's own credential store).
    market_openbb_provider: str = "yfinance"

    # Where fitted models are written. A named volume in Compose, so models
    # survive container replacement -- refitting on every deploy would be slow
    # and would silently change predictions.
    model_dir: str = "/models"

    quote_cache_seconds: int = 60
    # Daily bars only change once a day, so they cache far longer than quotes.
    candle_cache_seconds: int = 3600

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
