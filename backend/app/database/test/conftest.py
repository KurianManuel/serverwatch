"""Test fixtures for database tests."""

import sqlite3
import tempfile
from collections.abc import Callable, Generator
from pathlib import Path

import pytest

from app.database.connection import database_connection
from app.database.migrations import run_migrations


@pytest.fixture
def temp_db() -> Generator[str, None, None]:
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        yield db_path
    finally:
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def migrated_db(temp_db: str) -> str:
    """Create a database with migrations applied."""
    run_migrations(temp_db)
    return temp_db


@pytest.fixture
def db_connection(migrated_db: str) -> Generator[sqlite3.Connection, None, None]:
    """Provide a database connection to a migrated database."""
    with database_connection(migrated_db) as conn:
        yield conn


@pytest.fixture
def get_table_columns() -> Callable[[sqlite3.Connection, str], list[str]]:
    """Fixture to get column names for a table."""
    def _get_table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return [row[1] for row in cursor.fetchall()]
    return _get_table_columns


@pytest.fixture
def get_indexes() -> Callable[[sqlite3.Connection, str], list[str]]:
    """Fixture to get index names for a table."""
    def _get_indexes(conn: sqlite3.Connection, table: str) -> list[str]:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,)
        )
        return [row[0] for row in cursor.fetchall()]
    return _get_indexes


@pytest.fixture
def table_exists() -> Callable[[sqlite3.Connection, str], bool]:
    """Fixture to check if a table exists."""
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        cursor = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return cursor.fetchone() is not None
    return _table_exists
