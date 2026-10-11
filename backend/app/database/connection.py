"""SQLite connection management with PRAGMA configuration."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.database.config import DBConfig, get_db_config


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply SQLite PRAGMA settings for WAL mode and performance."""
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA wal_autocheckpoint=1000;")
    conn.execute("PRAGMA mmap_size=268435456;")  # 256 MB


@contextmanager
def database_connection(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """
    Create a short-lived database connection with PRAGMAs applied.

    Args:
        db_path: Optional database path. Uses config default if not provided.

    Yields:
        sqlite3.Connection with row_factory=sqlite3.Row and PRAGMAs applied.
    """
    config = get_db_config() if db_path is None else DBConfig(db_path=db_path)
    path = db_path or config.db_path

    # Ensure parent directory exists
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    try:
        yield conn
    finally:
        conn.close()
