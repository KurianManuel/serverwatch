"""FastAPI dependency injection providers."""

from functools import lru_cache

from app.config import Settings, settings


@lru_cache
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return settings
