"""Database migrations."""

import sqlite3
from app.database.connection import database_connection


MIGRATIONS = {
    1: "Initial schema",
}


def get_current_version() -> int:
    with database_connection() as conn:  # type: sqlite3.Connection
        cursor = conn.execute("SELECT MAX(version) FROM schema_metadata")
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else 0


def apply_migrations() -> None:
    current = get_current_version()
    for version in range(current + 1, max(MIGRATIONS.keys()) + 1):
        if version in MIGRATIONS:
            with database_connection() as conn:  # type: sqlite3.Connection
                conn.execute(
                    "INSERT INTO schema_metadata (version, description) VALUES (?, ?)",
                    (version, MIGRATIONS[version]),
                )
                conn.commit()