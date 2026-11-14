"""All service state: read from memory, written through to SQLite (app.db) first (§10,
stage-3 "Restarts").

State is only mutated in synchronous sections (no ``await`` between read and write), so
on the single event loop every request sees the state as if requests ran one at a time
(§11). A section that changes state runs inside ``Store.transaction()``: the change is on
disk before the section ends and so before any response that depends on it. Reset and
import swap in a fresh ``State`` and bump ``generation``; a build that started under an
older generation writes nothing (§3.3).
"""
from __future__ import annotations

import json
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from app.db import Database, Writer
from app.errors import ApiError
from app.fields import ALL_FIELDS, empty_fields


@dataclass
class User:
    id: str
    email: str
    display_name: str
    password_hash: str  # "scrypt$<salt hex>$<hash hex>"


@dataclass
class BuildRecord:
    """One finished build of a dossier (stage 3): its time (§8), outcome and spending and,
    for a ready build, the seven fields it decided and every page it read (URL and
    `true_from`), which with the fields' candidates are its page versions."""
    number: int                     # build order within the dossier, from 1
    time: str                       # RFC 3339, as the clock read it
    outcome: str                    # "ready" or "failed"
    spent_units: int
    fields: dict | None = None      # ready builds only
    pages: list[dict] = field(default_factory=list)   # [{"url", "true_from"}]

    def as_json(self) -> dict:
        return {"number": self.number, "time": self.time, "outcome": self.outcome,
                "spent_units": self.spent_units, "fields": self.fields, "pages": self.pages}

    @classmethod
    def from_json(cls, data: dict) -> "BuildRecord":
        return cls(data["number"], data["time"], data["outcome"], data["spent_units"],
                   data["fields"], data["pages"])


def empty_history() -> dict:
    return {name: [] for name in ALL_FIELDS}


@dataclass
class Dossier:
    id: str
    domain: str
    outcome: str = "failed"           # outcome of the last completed build
    fields: dict = field(default_factory=empty_fields)
    researched_at: str | None = None  # time of the last build that completed ready
    spent_units: int = 0              # units of every finished build (and imported spend)
    builds: list[BuildRecord] = field(default_factory=list)
    history: dict = field(default_factory=empty_history)
    build: object | None = None       # the running build, if any (app.build.Build)

    def live_spent(self) -> int:
        return self.spent_units + (self.build.budget.charged if self.build else 0)

    def state(self) -> str:
        return "building" if self.build is not None else self.outcome

    def summary(self) -> dict:
        return {"dossier_id": self.id, "domain": self.domain, "state": self.state()}

    def view(self) -> dict:
        return {**self.summary(), "researched_at": self.researched_at,
                "spent_units": self.live_spent(), "fields": self.fields}

    def ready_builds(self) -> list[BuildRecord]:
        return [b for b in self.builds if b.outcome == "ready"]

    def imported_spent(self) -> int:
        """Spending carried over from an import that is not part of any kept build."""
        return self.spent_units - sum(b.spent_units for b in self.builds)


@dataclass
class Batch:
    """A batch of builds under one shared budget (stage-4 "Batches")."""
    id: str
    user_id: str
    budget_units: int
    domains: list[str]               # normalised, in the order given
    started: list[str]               # the domains whose first build the batch started
    spent_units: int = 0             # durable: units reserved by its builds (app.budget)
    budget: object | None = None     # app.budget.BatchBudget while this process runs it

    def as_json(self) -> dict:
        return {"batch_id": self.id, "user_id": self.user_id, "budget_units": self.budget_units,
                "domains": self.domains, "started": self.started,
                "spent_units": self.spent_units}

    @classmethod
    def from_json(cls, data: dict) -> "Batch":
        return cls(data["batch_id"], data["user_id"], data["budget_units"], data["domains"],
                   data["started"], data["spent_units"])

    def spent(self) -> int:
        """Units its builds' provider calls cost: settled charges while it runs here, else
        the durable count (which may include calls in flight at a stop)."""
        return self.budget.charged if self.budget is not None else self.spent_units

    def running(self, state: "State") -> bool:
        return any(getattr(state.dossiers[d].build, "batch_id", None) == self.id
                   for d in self.started if d in state.dossiers)

    def view(self, state: "State") -> dict:
        return {"batch_id": self.id, "state": "running" if self.running(state) else "done",
                "budget_units": self.budget_units, "spent_units": self.spent(),
                "dossiers": [{"domain": d, "state": state.dossiers[d].state()
                              if d in state.dossiers else "failed"} for d in self.domains]}


@dataclass
class IdempotencyRecord:
    fingerprint: str
    status: int
    body: dict


@dataclass
class State:
    users: dict[str, User] = field(default_factory=dict)          # id -> user
    emails: dict[str, str] = field(default_factory=dict)          # casefolded email -> id
    tokens: dict[str, str] = field(default_factory=dict)          # sha256(token) -> user id
    dossiers: dict[str, Dossier] = field(default_factory=dict)    # domain -> dossier
    idempotency: dict[tuple, IdempotencyRecord] = field(default_factory=dict)
    feed: list[dict] = field(default_factory=list)                # change feed, by seq
    batches: dict[str, Batch] = field(default_factory=dict)       # id -> batch

    def new_id(self, prefix: str) -> str:
        taken = set(self.users) | {d.id for d in self.dossiers.values()} | set(self.batches)
        while True:
            candidate = f"{prefix}_{secrets.token_hex(8)}"
            if candidate not in taken:
                return candidate

    def add_user(self, user: User) -> None:
        self.users[user.id] = user
        self.emails[email_key(user.email)] = user.id

    def next_seq(self) -> int:
        return self.feed[-1]["seq"] + 1 if self.feed else 1


def email_key(email: str) -> str:
    return email.casefold()


class Store:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        self.state = load_state(self.db)
        self.generation = 0

    @contextmanager
    def transaction(self) -> Iterator[Writer]:
        """Write a state change durably. Change memory inside the block, after validating;
        if the write fails, memory is reloaded from the database so it never runs ahead."""
        try:
            with self.db.transaction() as writer:
                yield writer
        except ApiError:  # a refusal raised before any change: nothing to undo
            raise
        except BaseException:
            self.replace(load_state(self.db))
            raise

    def replace(self, state: State) -> None:
        self.state = state
        self.generation += 1


def load_state(db: Database) -> State:
    """The state the database holds (no build is running after a load)."""
    state = State()
    for uid, email, display_name, password_hash in db.rows(
            "SELECT id, email, display_name, password_hash FROM users ORDER BY rowid"):
        state.add_user(User(uid, email, display_name, password_hash))
    for digest, user_id in db.rows("SELECT digest, user_id FROM tokens ORDER BY rowid"):
        state.tokens[digest] = user_id
    by_id = {}
    for domain, did, outcome, researched_at, spent, fields in db.rows(
            "SELECT domain, id, outcome, researched_at, spent_units, fields FROM dossiers "
            "ORDER BY rowid"):
        dossier = Dossier(did, domain, outcome, json.loads(fields), researched_at, spent)
        state.dossiers[domain] = by_id[did] = dossier
    for did, build in db.rows("SELECT dossier_id, build FROM builds ORDER BY dossier_id, number"):
        by_id[did].builds.append(BuildRecord.from_json(json.loads(build)))
    for did, name, entry in db.rows("SELECT dossier_id, field, entry FROM history ORDER BY n"):
        by_id[did].history[name].append(json.loads(entry))
    state.feed = [json.loads(entry) for (entry,) in db.rows("SELECT entry FROM feed ORDER BY seq")]
    for user_id, method, path, key, print_, status, body in db.rows(
            "SELECT user_id, method, path, key, fingerprint, status, body FROM idempotency "
            "ORDER BY rowid"):
        state.idempotency[(user_id, method, path, key)] = IdempotencyRecord(
            print_, status, json.loads(body))
    for (batch,) in db.rows("SELECT batch FROM batches ORDER BY rowid"):
        loaded = Batch.from_json(json.loads(batch))
        state.batches[loaded.id] = loaded
    return state


@dataclass(frozen=True)
class Interrupted:
    """A build that was in flight when the service last stopped (app.commit recovers it)."""
    dossier_id: str
    build_time: str
    batch_id: str | None
    spent: int


def interrupted_builds(db: Database) -> list[Interrupted]:
    return [Interrupted(*row) for row in db.rows(
        "SELECT dossier_id, build_time, batch_id, spent FROM running ORDER BY rowid")]
