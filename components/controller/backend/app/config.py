"""
Configuration module for the HAMq Controller.

All settings are loaded from environment variables with sensible defaults.
This allows the service to be configured via Kubernetes ConfigMaps/Secrets
without any code changes (12-factor app pattern).
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """
    Central configuration class using pydantic-settings.

    All values can be overridden by environment variables (case-insensitive).
    Example: KAFKA_NAMESPACE=my-kafka sets the Kafka namespace.
    """

    # -------------------------------------------------------------------------
    # Kubernetes client settings
    # -------------------------------------------------------------------------
    # When running inside a pod the controller uses the mounted service account
    # token at /var/run/secrets/kubernetes.io/serviceaccount.  For local
    # development set K8S_IN_CLUSTER=false and provide a kubeconfig path.
    K8S_IN_CLUSTER: bool = Field(
        default=True,
        description="Use in-cluster service account auth (set False for local dev)"
    )
    K8S_KUBECONFIG_PATH: str = Field(
        default="",
        description="Path to a kubeconfig file; only used when K8S_IN_CLUSTER=False"
    )

    # -------------------------------------------------------------------------
    # Kafka namespace and pod targeting
    # -------------------------------------------------------------------------
    KAFKA_NAMESPACE: str = Field(
        default="kafka",
        description="Kubernetes namespace where the Kafka StatefulSet runs"
    )
    KAFKA_CLUSTER_NAME: str = Field(
        default="hamq-kafka",
        description="Strimzi cluster name (used to build resource names)"
    )
    # Strimzi sets this label on all broker pods so we can filter precisely
    KAFKA_POD_LABEL_SELECTOR: str = Field(
        default="strimzi.io/name=hamq-kafka-kafka",
        description="Label selector to identify Kafka broker pods"
    )

    # -------------------------------------------------------------------------
    # HAMq application namespace
    # -------------------------------------------------------------------------
    HAMQ_NAMESPACE: str = Field(
        default="hamq",
        description="Namespace for the producer/consumer/arbiter pods"
    )

    # -------------------------------------------------------------------------
    # Chaos engine settings
    # -------------------------------------------------------------------------
    CHAOS_ENABLED: bool = Field(
        default=True,
        description="Master switch — set False to disable all chaos operations"
    )
    # Cron expression for automatic chaos injection.  Empty string disables it.
    # Example: "*/30 * * * *" = every 30 minutes
    CHAOS_SCHEDULE_CRON: str = Field(
        default="",
        description="Cron expression for automatic chaos; empty = no auto-chaos"
    )
    # Safety guard: don't allow chaos events closer than this many seconds apart
    CHAOS_MIN_INTERVAL_S: int = Field(
        default=60,
        description="Minimum seconds between consecutive chaos events"
    )
    CHAOS_TARGET_NAMESPACE: str = Field(
        default="kafka",
        description="Namespace in which chaos operations (pod delete, partition) are performed"
    )

    # -------------------------------------------------------------------------
    # HAMq component API URLs (for databus metrics aggregation)
    # -------------------------------------------------------------------------
    PRODUCER_API_URL: str = Field(
        default="http://hamq-producer.hamq.svc.cluster.local:8000",
        description="Base URL of the producer FastAPI service"
    )
    CONSUMER_API_URL: str = Field(
        default="http://hamq-consumer.hamq.svc.cluster.local:8001",
        description="Base URL of the consumer FastAPI service"
    )
    DATABUS_POLL_TIMEOUT_S: float = Field(
        default=2.0,
        description="HTTP timeout in seconds when fetching producer/consumer metrics"
    )
    DATABUS_AUTH_USERNAME: str = Field(
        default="admin",
        description="Username for basic-auth against the producer/consumer APIs"
    )
    DATABUS_AUTH_PASSWORD: str = Field(
        default="admin",
        description="Password for basic-auth against the producer/consumer APIs"
    )

    # -------------------------------------------------------------------------
    # Controller identity and persistence
    # -------------------------------------------------------------------------
    CONTROLLER_ID: str = Field(
        default="controller-1",
        description="Unique identifier for this controller instance"
    )
    DB_PATH: str = Field(
        default="/data/controller_events.db",
        description="Filesystem path for the SQLite audit-log database"
    )

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------
    AUTH_USERNAME: str = Field(
        default="admin",
        description="API username"
    )
    # Default hash is bcrypt of "admin" — MUST be changed in production.
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
        default=8003,
        description="TCP port for the uvicorn server"
    )
    CORS_ORIGINS: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins (or '*' for all)"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # Accept unknown env vars without raising a validation error
        "extra": "ignore",
    }


# Module-level singleton — import this everywhere instead of re-instantiating
settings = Settings()
