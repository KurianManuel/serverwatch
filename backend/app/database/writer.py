"""Database writer - batched async writes."""

import asyncio
import sqlite3
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from app.config import settings
from app.database.connection import database_connection


class WritePriority(int, Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class WriteTask:
    priority: WritePriority
    table: str
    data: dict[str, Any]
    callback: Callable[[bool], None] | None = None
    timestamp: datetime = datetime.utcnow()


class DatabaseWriter:
    def __init__(self) -> None:
        self._queue: deque[WriteTask] = deque(maxlen=settings.db_queue_size)
        self._batch_size = settings.db_batch_size
        self._flush_interval = settings.db_flush_interval
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._writer_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            await self._task

    async def write(self, table: str, data: dict[str, Any], priority: WritePriority = WritePriority.NORMAL) -> bool:
        maxlen = self._queue.maxlen
        if maxlen is not None and len(self._queue) >= maxlen:
            if priority <= WritePriority.NORMAL:
                return False
            min_priority_idx = min(range(len(self._queue)), key=lambda i: self._queue[i].priority)
            self._queue.remove(self._queue[min_priority_idx])

        task = WriteTask(priority=priority, table=table, data=data)
        self._queue.append(task)
        return True

    async def _writer_loop(self) -> None:
        while self._running:
            try:
                await self._flush_batch()
            except Exception:
                pass
            await asyncio.sleep(self._flush_interval)

    async def _flush_batch(self) -> None:
        if not self._queue:
            return

        batch = sorted(self._queue, key=lambda t: t.priority, reverse=True)[: self._batch_size]
        if not batch:
            return

        with database_connection() as conn:  # type: sqlite3.Connection
            for task in batch:
                try:
                    self._execute_insert(conn, task.table, task.data)
                    if task.callback:
                        task.callback(True)
                except Exception:
                    if task.callback:
                        task.callback(False)
            conn.commit()

        for task in batch:
            if task in self._queue:
                self._queue.remove(task)

    def _execute_insert(self, conn: sqlite3.Connection, table: str, data: dict[str, Any]) -> None:
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        values = tuple(data.values())
        conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values)

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    @property
    def is_healthy(self) -> bool:
        maxlen = self._queue.maxlen
        if maxlen is None:
            return self._running
        return self._running and self.queue_depth < maxlen * 0.9


db_writer = DatabaseWriter()
