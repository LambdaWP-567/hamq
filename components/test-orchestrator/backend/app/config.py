from __future__ import annotations

import os
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = Field(default="localhost:9092")
    KAFKA_TOPIC: str = Field(default="hamq-test-counter")
    KAFKA_TLS_ENABLED: bool = Field(default=False)
    KAFKA_CA_CERT_PATH: str = Field(default="")
    KAFKA_CLIENT_CERT_PATH: str = Field(default="")
    KAFKA_CLIENT_KEY_PATH: str = Field(default="")

    # Counter test
    COUNTER_MAX: int = Field(default=10000)
    FREQ_HZ: float = Field(default=10.0)
    AUTOSTART: bool = Field(default=False)

    # Auth
    AUTH_USERNAME: str = Field(default="admin")
    AUTH_PASSWORD_HASH: str = Field(
        default="$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TiGhYp.dKjQFhYVWMxJYBv9L2.Ry"
    )
    AUTH_SECRET_KEY: str = Field(default="change-me-in-production-please")
    AUTH_TOKEN_EXPIRE_MINUTES: int = Field(default=1440)

    CORS_ORIGINS: str = Field(default="*")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
