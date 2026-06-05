"""
Configuration module for the HAMq Arbiter.

All settings are loaded from environment variables with sensible defaults.
This allows the service to be configured via Kubernetes ConfigMaps/Secrets
without any code changes — following the 12-factor app methodology.

In production, override sensitive values (AUTH_SECRET_KEY, AUTH_PASSWORD_HASH,
PRODUCER_API_TOKEN, CONSUMER_API_TOKEN) via Kubernetes Secrets mounted as
environment variables.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """
    Central configuration class using pydantic-settings.

    All values can be overridden by environment variables (case-insensitive).
    Example: PRODUCER_API_URLS=http://... overrides the default.

    The Arbiter connects to the Producer and Consumer REST APIs — it does NOT
    connect directly to Kafka, so no TLS certificate settings are needed here.
    """

    # -------------------------------------------------------------------------
    # Producer API connectivity
    # -------------------------------------------------------------------------
    # Comma-separated list of producer base URLs.  When multiple producers run
    # in parallel (e.g., a StatefulSet with 3 replicas), list all of them here
    # so the Arbiter polls each one and aggregates per-producer audit results.
    PRODUCER_API_URLS: str = Field(
        default="http://hamq-producer.hamq.svc.cluster.local:8000",
        description=(
            "Comma-separated list of Producer API base URLs. "
            "Example: http://producer-0:8000,http://producer-1:8000"
        )
    )
    PRODUCER_API_TOKEN: str = Field(
        default="",
        description="Static JWT bearer token for Producer API (overrides auto-login)"
    )
    PRODUCER_API_USERNAME: str = Field(
        default="admin",
        description="Username for Producer API auto-login"
    )
    PRODUCER_API_PASSWORD: str = Field(
        default="admin",
        description="Password for Producer API auto-login"
    )

    # -------------------------------------------------------------------------
    # Consumer API connectivity
    # -------------------------------------------------------------------------
    CONSUMER_API_URL: str = Field(
        default="http://hamq-consumer.hamq.svc.cluster.local:8001",
        description="Base URL of the Consumer REST API"
    )
    CONSUMER_API_TOKEN: str = Field(
        default="",
        description="Static JWT bearer token for Consumer API (overrides auto-login)"
    )
    CONSUMER_API_USERNAME: str = Field(
        default="admin",
        description="Username for Consumer API auto-login"
    )
    CONSUMER_API_PASSWORD: str = Field(
        default="admin",
        description="Password for Consumer API auto-login"
    )

    # -------------------------------------------------------------------------
    # Arbiter identity
    # -------------------------------------------------------------------------
    ARBITER_ID: str = Field(
        default="arbiter-1",
        description="Unique identifier for this Arbiter instance (used in reports and metrics)"
    )

    # -------------------------------------------------------------------------
    # SQLite audit store
    # -------------------------------------------------------------------------
    # Mount a PersistentVolume at /data in Kubernetes to survive pod restarts
    # and preserve historical audit results across deployments.
    DB_PATH: str = Field(
        default="/data/arbiter_audits.db",
        description="Filesystem path for the SQLite audit database"
    )

    # -------------------------------------------------------------------------
    # Reconciliation engine
    # -------------------------------------------------------------------------
    # How often the background reconcile loop runs.
    RECONCILE_INTERVAL_S: float = Field(
        default=10.0,
        ge=1.0,
        description="Interval in seconds between automatic reconciliation passes"
    )
    # How many trailing sequence numbers to examine each reconciliation pass.
    # Larger windows catch more historical gaps but require more memory and API
    # response size.  1 000 is a safe default for most workloads.
    RECONCILE_LOOKBACK_MESSAGES: int = Field(
        default=1000,
        ge=10,
        description="Number of most-recent sequences to include in each reconcile window"
    )

    # -------------------------------------------------------------------------
    # Alerting
    # -------------------------------------------------------------------------
    # Loss rates above this threshold trigger alert events and webhook calls.
    # 0.01 = 1%.  Set to 0 to alert on any loss whatsoever.
    ALERT_LOSS_RATE_THRESHOLD: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Loss-rate fraction above which an alert is emitted (0.01 = 1%)"
    )
    # Optional HTTP endpoint to POST AlertEvent payloads to.
    # Leave blank to disable webhook alerting.
    ALERT_WEBHOOK_URL: str = Field(
        default="",
        description="HTTP(S) URL to POST alert events to; leave blank to disable"
    )

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------
    AUTH_USERNAME: str = Field(
        default="admin",
        description="API username for JWT login"
    )
    # Default hash is bcrypt of "admin" — MUST be changed in production.
    # Generate with: python -c "import bcrypt; print(bcrypt.hashpw(b'secret', bcrypt.gensalt()).decode())"
    AUTH_PASSWORD_HASH: str = Field(
        default="$2b$12$SHeIYmhukN6bQiD34QFFGOG3hw49eXplUSEqjwCzgJKQCphfNl1mi",
        description="bcrypt hash of the API password — default is bcrypt('admin')"
    )
    AUTH_SECRET_KEY: str = Field(
        default="change-me-in-production",
        description="HMAC secret key for JWT signing — MUST be rotated in production"
    )
    AUTH_TOKEN_EXPIRE_MINUTES: int = Field(
        default=1440,
        description="JWT token validity in minutes (default: 24 hours)"
    )

    # -------------------------------------------------------------------------
    # API server
    # -------------------------------------------------------------------------
    API_HOST: str = Field(
        default="0.0.0.0",
        description="Host address for the uvicorn server"
    )
    API_PORT: int = Field(
        default=8002,
        description="TCP port for the uvicorn server"
    )
    CORS_ORIGINS: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins (or '*' for all)"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # Ignore unknown env vars that may come from the pod environment
        "extra": "ignore",
    }


# Module-level singleton — import this everywhere instead of re-instantiating.
settings = Settings()
