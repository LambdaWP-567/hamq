"""
HAMq Consumer — Configuration
==============================
All settings are sourced from environment variables (12-factor app).
Pydantic-Settings provides automatic env-var binding, type coercion,
and validation so no mutable global state is needed.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ------------------------------------------------------------------ #
    #  Kafka connectivity
    # ------------------------------------------------------------------ #
    # Bootstrap servers for the Kafka cluster.
    # Kubernetes Service DNS name is used by default; override for external
    # access via the LoadBalancer endpoint.
    KAFKA_BOOTSTRAP_SERVERS: str = (
        "hamq-kafka-bootstrap.kafka.svc.cluster.local:9093"
    )

    # Topic from which this consumer reads messages.
    KAFKA_TOPIC: str = "hamq-messages"

    # Consumer group identifier – all instances share this group so Kafka
    # distributes topic partitions across replicas automatically.
    KAFKA_CONSUMER_GROUP_ID: str = "hamq-consumer-group"

    # Enable TLS/mTLS encryption for the Kafka connection.
    KAFKA_TLS_ENABLED: bool = True

    # Paths to the TLS material mounted from Strimzi-generated Secrets.
    KAFKA_CA_CERT_PATH: str = "/certs/ca.crt"
    KAFKA_CLIENT_CERT_PATH: str = "/certs/user.crt"
    KAFKA_CLIENT_KEY_PATH: str = "/certs/user.key"

    # Where to start reading when no committed offset exists for this
    # consumer group.  "earliest" = read from the beginning of the topic.
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"

    # Manual offset commit: we commit only *after* a message has been
    # successfully persisted to SQLite (at-least-once semantics).
    KAFKA_ENABLE_AUTO_COMMIT: bool = False

    # Maximum number of records returned per poll call.
    KAFKA_MAX_POLL_RECORDS: int = 500

    # ------------------------------------------------------------------ #
    #  Consumer instance identity
    # ------------------------------------------------------------------ #
    # Logical name for this consumer instance (used in Prometheus labels
    # and the /api/status response).
    CONSUMER_ID: str = "consumer-1"

    # ------------------------------------------------------------------ #
    #  SQLite persistence
    # ------------------------------------------------------------------ #
    # Path to the SQLite database file.  Mount a PersistentVolume at /data
    # in Kubernetes to survive pod restarts.
    DB_PATH: str = "/data/consumer_messages.db"

    # How long to keep received messages in the database before pruning.
    # Default is 7 days (168 hours).
    DB_RETENTION_HOURS: int = 168

    # ------------------------------------------------------------------ #
    #  Authentication
    # ------------------------------------------------------------------ #
    # HTTP Basic-style username that clients must supply to obtain a JWT.
    AUTH_USERNAME: str = "admin"

    # Bcrypt hash of the password.  Generate a new one with:
    #   python -c "from passlib.hash import bcrypt; print(bcrypt.hash('secret'))"
    AUTH_PASSWORD_HASH: str = (
        "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TiGhYp.dKjQFhYVWMxJYBv9L2.Ry"
    )

    # HMAC signing secret for JWTs.  Must be changed in production.
    AUTH_SECRET_KEY: str = "change-me-in-production"

    # JWT validity window in minutes (default: 24 hours).
    AUTH_TOKEN_EXPIRE_MINUTES: int = 1440

    # ------------------------------------------------------------------ #
    #  API server
    # ------------------------------------------------------------------ #
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8001

    # Comma-separated list of allowed CORS origins, or "*" for any.
    CORS_ORIGINS: str = "*"

    class Config:
        # Allow environment variables to override defaults.
        env_file = ".env"
        env_file_encoding = "utf-8"


# Module-level singleton — import this everywhere instead of re-instantiating.
settings = Settings()
