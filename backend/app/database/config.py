"""Database configuration for ServerWatch."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DBConfig:
    """Database configuration settings."""
    db_path: str = "/var/lib/serverwatch/serverwatch.db"
    queue_size: int = 1000
    batch_size: int = 50
    flush_interval: float = 1.0
    retention_raw_hours: int = 24
    retention_1min_days: int = 7
    retention_5min_days: int = 30
    retention_1h_days: int = 365
    retention_1d_days: int = 730


def get_db_config() -> DBConfig:
    """Get database configuration from settings."""
    from app.config import settings
    return DBConfig(
        db_path=settings.database_path,
        queue_size=settings.db_queue_size,
        batch_size=settings.db_batch_size,
        flush_interval=settings.db_flush_interval,
        retention_raw_hours=settings.retention_raw_hours,
        retention_1min_days=settings.retention_1min_days,
        retention_5min_days=settings.retention_5min_days,
        retention_1h_days=settings.retention_1h_days,
        retention_1d_days=settings.retention_1d_days,
    )
