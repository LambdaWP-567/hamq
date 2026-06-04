"""
Configuration module for the HAMq Producer.

All settings are loaded from environment variables with sensible defaults.
This allows the service to be configured via Kubernetes ConfigMaps/Secrets
without any code changes.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """
    Central configuration class using pydantic-settings.

    All values can be overridden by environment variables (case-insensitive).
    Example: KAFKA_BOOTSTRAP_SERVERS=... sets the kafka bootstrap servers.
    """

    # -------------------------------------------------------------------------
    # Kafka connection settings
    # -------------------------------------------------------------------------
    # DNS-based bootstrap — survives pod restarts and IP changes in K8s
    KAFKA_BOOTSTRAP_SERVERS: str = Field(
        default="hamq-kafka-bootstrap.kafka.svc.cluster.local:9093",
        description="Kafka bootstrap server list (comma-separated host:port pairs)"
    )
    KAFKA_TOPIC: str = Field(
        default="hamq-messages",
        description="Topic to which the producer publishes messages"
    )
    KAFKA_TLS_ENABLED: bool = Field(
        default=True,
        description="Enable mutual-TLS for Kafka connections (required in production)"
    )
    KAFKA_CA_CERT_PATH: str = Field(
        default="/certs/ca.crt",
        description="Path to the Kafka cluster CA certificate"
    )
    KAFKA_CLIENT_CERT_PATH: str = Field(
        default="/certs/user.crt",
        description="Path to the client TLS certificate for mTLS authentication"
    )
    KAFKA_CLIENT_KEY_PATH: str = Field(
        default="/certs/user.key",
        description="Path to the client TLS private key"
    )
    # acks=all guarantees the message is written to all ISR replicas before ack
    KAFKA_ACKS: str = Field(
        default="all",
        description="Required acknowledgements: 'all' for maximum durability"
    )
    KAFKA_MAX_BATCH_SIZE: int = Field(
        default=16384,
        description="Maximum size in bytes of a single Kafka batch"
    )
    # Small linger gives batching benefit without adding noticeable latency
    KAFKA_LINGER_MS: int = Field(
        default=5,
        description="Milliseconds to wait before sending a partial batch"
    )
    KAFKA_REQUEST_TIMEOUT_MS: int = Field(
        default=30000,
        description="Kafka request timeout in milliseconds"
    )
    KAFKA_RETRY_BACKOFF_MS: int = Field(
        default=200,
        description="Backoff in ms between Kafka retry attempts"
    )
    # Effectively infinite retries — the local buffer provides resilience
    # while Kafka is unavailable; when it comes back, we flush in order.
    KAFKA_MAX_RETRIES: int = Field(
        default=2147483647,
        description="Maximum number of Kafka send retries (2^31-1 ≈ infinite)"
    )

    # -------------------------------------------------------------------------
    # Producer identity and behaviour
    # -------------------------------------------------------------------------
    PRODUCER_ID: str = Field(
        default="producer-1",
        description="Unique identifier for this producer instance (used in messages)"
    )
    PRODUCER_FREQUENCY_HZ: float = Field(
        default=1.0,
        ge=0.001,
        le=1000.0,
        description="Message generation frequency in messages per second (1–1000)"
    )
    PRODUCER_AUTOSTART: bool = Field(
        default=False,
        description="Automatically start producing on service startup"
    )

    # -------------------------------------------------------------------------
    # Local SQLite buffer — the key resilience mechanism
    # -------------------------------------------------------------------------
    # Messages are written here first; a background task flushes them to Kafka.
    # If Kafka is unavailable the buffer keeps accumulating up to BUFFER_MAX_SIZE.
    BUFFER_DB_PATH: str = Field(
        default="/data/producer_buffer.db",
        description="Filesystem path for the SQLite buffer database"
    )
    BUFFER_MAX_SIZE: int = Field(
        default=100000,
        description="Maximum number of messages to keep in the local buffer"
    )
    BUFFER_FLUSH_INTERVAL_S: float = Field(
        default=1.0,
        description="How often (in seconds) to attempt flushing the buffer to Kafka"
    )
    BUFFER_RETRY_INTERVAL_S: float = Field(
        default=5.0,
        description="How often (in seconds) to attempt Kafka reconnection"
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
        default="change-me-in-production-use-a-random-32-char-string",
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
        default=8000,
        description="TCP port for the uvicorn server"
    )
    CORS_ORIGINS: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins (or '*' for all)"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # Allow extra fields from .env without raising validation errors
        "extra": "ignore",
    }


# Module-level singleton — import this everywhere instead of re-instantiating
settings = Settings()
