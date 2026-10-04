"""Servers repository."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3  # noqa: F401

import uuid

from app.database.connection import database_connection


class ServersRepository:
    def get_or_create_server(self, hostname: str) -> str:
        with database_connection() as conn:  # type: "sqlite3.Connection"
            cursor = conn.execute("SELECT id FROM servers WHERE hostname = ?", (hostname,))
            row = cursor.fetchone()
            if row:
                return str(row["id"])

            server_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO servers (id, hostname) VALUES (?, ?)",
                (server_id, hostname),
            )
            conn.commit()
            return server_id

    def get_server(self, server_id: str) -> Any | None:
        with database_connection() as conn:  # type: "sqlite3.Connection"
            cursor = conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
            return cursor.fetchone()


servers_repository = ServersRepository()
