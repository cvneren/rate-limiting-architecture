import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Default Rate Limit: 100 requests per 60 seconds
    RATE_LIMIT_LIMIT: int = 100
    RATE_LIMIT_PERIOD: int = 60
    RATE_LIMIT_BURST: int = 10  # Allow burst of 10


settings = Settings()
