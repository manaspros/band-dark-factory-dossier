"""Durable state: one SQLite file, written before any response that depends on it (stage-3
"Restarts").

SQLite runs in WAL mode with ``synchronous=FULL``: a transaction is on disk when COMMIT
returns, and a crash at any point leaves either all of a transaction or none of it. Every
state change is one transaction (``Database.transaction``); handlers run it synchronously,
with no ``await`` inside, so on the single event loop requests stay serialisable (§11).

Rows hold JSON for the nested parts (fields, builds, history and feed entries, idempotent
responses). ``load`` rebuilds the in-memory ``State`` the handlers read from.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL,
    display_name TEXT NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tokens (digest TEXT PRIMARY KEY, user_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dossiers (domain TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE,
    outcome TEXT NOT NULL, researched_at TEXT, spent_units INTEGER NOT NULL,
    fields TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS builds (dossier_id TEXT NOT NULL, number INTEGER NOT NULL,
    build TEXT NOT NULL, PRIMARY KEY (dossier_id, number));
CREATE TABLE IF NOT EXISTS history (n INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id TEXT NOT NULL, field TEXT NOT NULL, entry TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feed (seq INTEGER PRIMARY KEY, entry TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, batch TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS running (dossier_id TEXT PRIMARY KEY, build_time TEXT NOT NULL,
    batch_id TEXT, spent INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency (user_id TEXT NOT NULL, method TEXT NOT NULL,
    path TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL, status INTEGER NOT NULL,
    body TEXT NOT NULL, PRIMARY KEY (user_id, method, path, key));
"""
_TABLES = ("meta", "users", "tokens", "dossiers", "builds", "history", "feed", "idempotency",
           "batches", "running")


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Writer:
    """The writes of one open transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def set_clock(self, now: str | None) -> None:
        self._conn.execute("INSERT INTO meta (key, value) VALUES ('clock', ?) "
                           "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (now,))

    def put_user(self, user) -> None:
        self._conn.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                           (user.id, user.email, user.display_name, user.password_hash))

    def put_token(self, digest: str, user_id: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO tokens VALUES (?, ?)", (digest, user_id))

    def put_dossier(self, dossier) -> None:
        """Insert or update the dossier's current state (its row keeps its place)."""
        self._conn.execute(
            "INSERT INTO dossiers VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(domain) DO UPDATE SET "
            "outcome = excluded.outcome, researched_at = excluded.researched_at, "
            "spent_units = excluded.spent_units, fields = excluded.fields",
            (dossier.domain, dossier.id, dossier.outcome, dossier.researched_at,
             dossier.spent_units, _dump(dossier.fields)))

    def add_build(self, dossier_id: str, build) -> None:
        self._conn.execute("INSERT INTO builds VALUES (?, ?, ?)",
                           (dossier_id, build.number, _dump(build.as_json())))

    def add_history(self, dossier_id: str, field: str, entry: dict) -> None:
        self._conn.execute("INSERT INTO history (dossier_id, field, entry) VALUES (?, ?, ?)",
                           (dossier_id, field, _dump(entry)))

    def add_feed(self, entry: dict) -> None:
        self._conn.execute("INSERT INTO feed VALUES (?, ?)", (entry["seq"], _dump(entry)))

    def put_batch(self, batch) -> None:
        self._conn.execute("INSERT INTO batches VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET "
                           "batch = excluded.batch", (batch.id, _dump(batch.as_json())))

    def put_running(self, dossier_id: str, build_time: str, batch_id: str | None) -> None:
        """A build has started: until it is recorded, it is in flight (stage-4 Restarts)."""
        self._conn.execute("INSERT OR REPLACE INTO running VALUES (?, ?, ?, 0)",
                           (dossier_id, build_time, batch_id))

    def set_running_spent(self, dossier_id: str, spent: int) -> None:
        self._conn.execute("UPDATE running SET spent = ? WHERE dossier_id = ?",
                           (spent, dossier_id))

    def delete_running(self, dossier_id: str) -> None:
        self._conn.execute("DELETE FROM running WHERE dossier_id = ?", (dossier_id,))

    def put_idempotency(self, key: tuple, record) -> None:
        self._conn.execute("INSERT OR REPLACE INTO idempotency VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (*key, record.fingerprint, record.status, _dump(record.body)))

    def put_state(self, state) -> None:
        """Replace every row but the clock with ``state``."""
        for table in _TABLES:
            if table != "meta":
                self._conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed names
        for user in state.users.values():
            self.put_user(user)
        for digest, user_id in state.tokens.items():
            self.put_token(digest, user_id)
        for dossier in state.dossiers.values():
            self.put_dossier(dossier)
            for build in dossier.builds:
                self.add_build(dossier.id, build)
            for field, entries in dossier.history.items():
                for entry in entries:
                    self.add_history(dossier.id, field, entry)
        for entry in state.feed:
            self.add_feed(entry)
        for key, record in state.idempotency.items():
            self.put_idempotency(key, record)
        for batch in state.batches.values():
            self.put_batch(batch)


class Database:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[Writer]:
        """One atomic, durable write: committed when the block ends, rolled back on error."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield Writer(self._conn)
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def rows(self, sql: str) -> list[tuple]:
        return self._conn.execute(sql).fetchall()

    def clock(self) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'clock'").fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self._conn.close()
