"""Append-only SQLite event log. The log is the only store: engine state is a replay of it.

Rows are never updated or deleted (triggers enforce it). Only `wipe()` clears the log, by
dropping the table, and only the demo `reset` calls that.

Kinds written by the engine:
    edit_received   an edit arrived: prompt, diff stats, content hash, touched/blast
    finding_created a check raised a finding (secrets already redacted)
    decision        allow / hold / deny, with who decided (engine, human, timeout) and why
    verdict         a finding was confirmed or dismissed
    score_change    the score moved (delta != 0)
    activity        an outcome that did not move the score (held, blocked, allowed with findings)
    tier_change     the agent crossed a tier boundary
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Event:
    id: int
    t: float  # unix seconds
    kind: str
    data: dict


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    t    REAL NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;
"""


class EventLog:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._db.executescript(SCHEMA)
        self._db.commit()

    def append(self, kind: str, data: dict, t: float) -> Event:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO events (t, kind, data) VALUES (?, ?, ?)", (t, kind, payload))
            self._db.commit()
        return Event(cursor.lastrowid, t, kind, data)

    def all(self) -> list[Event]:
        with self._lock:
            rows = self._db.execute("SELECT id, t, kind, data FROM events ORDER BY id").fetchall()
        return [Event(i, t, kind, json.loads(data)) for i, t, kind, data in rows]

    def wipe(self) -> None:
        with self._lock:
            self._db.executescript("DROP TABLE IF EXISTS events;")
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()
