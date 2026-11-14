"""All service state, in memory, plus its export/import form (§10).

State is only mutated in synchronous sections (no ``await`` between read and write), so
on the single event loop every request sees the state as if requests ran one at a time
(§11). Reset and import swap in a fresh ``State`` and bump ``generation``; a build that
started under an older generation writes nothing (§3.3).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from app.errors import invalid
from app.evidence import empty_fields
from app.support import FIELDS


@dataclass
class User:
    id: str
    email: str
    display_name: str
    password_hash: str  # "scrypt$<salt hex>$<hash hex>"


@dataclass
class Dossier:
    id: str
    domain: str
    outcome: str = "failed"           # outcome of the last completed build
    fields: dict = field(default_factory=empty_fields)
    researched_at: str | None = None  # time of the last build that completed ready
    spent_units: int = 0              # units of every finished build
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

    def new_id(self, prefix: str) -> str:
        taken = set(self.users) | {d.id for d in self.dossiers.values()}
        while True:
            candidate = f"{prefix}_{secrets.token_hex(8)}"
            if candidate not in taken:
                return candidate

    def add_user(self, user: User) -> None:
        self.users[user.id] = user
        self.emails[email_key(user.email)] = user.id


def email_key(email: str) -> str:
    return email.casefold()


class Store:
    def __init__(self) -> None:
        self.state = State()
        self.generation = 0

    def replace(self, state: State) -> None:
        self.state = state
        self.generation += 1


# --------------------------------------------------------------------------- export / import

TRACK = "dossier"
FORMAT_VERSION = 1


def export_state(state: State) -> dict:
    """A JSON snapshot: committed dossiers only, never a running build's partial work."""
    return {
        "users": [{"id": u.id, "email": u.email, "display_name": u.display_name,
                   "password_hash": u.password_hash} for u in state.users.values()],
        "tokens": [{"token_sha256": t, "user_id": uid} for t, uid in state.tokens.items()],
        "dossiers": [{"dossier_id": d.id, "domain": d.domain, "state": d.outcome,
                      "fields": d.fields, "researched_at": d.researched_at,
                      "spent_units": d.spent_units} for d in state.dossiers.values()],
        "idempotency": [{"user_id": k[0], "method": k[1], "path": k[2], "key": k[3],
                         "fingerprint": r.fingerprint, "status": r.status, "body": r.body}
                        for k, r in state.idempotency.items()],
    }


def _require(condition: bool, what: str) -> None:
    if not condition:
        raise invalid(f"invalid state: {what}")


def _is_str(value, max_len: int | None = None, min_len: int = 0) -> bool:
    return isinstance(value, str) and len(value) >= min_len and (
        max_len is None or len(value) <= max_len)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_field(name: str, value) -> bool:
    if not isinstance(value, dict) or set(value) != {"value", "status", "citations"}:
        return False
    citations = value["citations"]
    if not isinstance(citations, list) or not all(
            isinstance(c, dict) and set(c) == {"url", "excerpt", "provider"}
            and all(_is_str(c[k]) for k in c) for c in citations):
        return False
    if value["value"] is None:
        return value["status"] == "unknown" and citations == []
    typed = _is_int(value["value"]) if name in ("founded_year", "funding_total") else _is_str(
        value["value"])
    return typed and value["status"] == "known" and len(citations) >= 1


def import_state(payload) -> State:
    """Validate an export completely, then build the State it describes; 422 otherwise."""
    _require(isinstance(payload, dict), "export must be an object")
    _require(payload.get("track") == TRACK, "track")
    version = payload.get("format_version")
    _require(_is_int(version) and version == FORMAT_VERSION, "format_version")
    raw = payload.get("state")
    _require(isinstance(raw, dict), "state")
    for key in ("users", "tokens", "dossiers", "idempotency"):
        _require(isinstance(raw.get(key), list), key)

    state = State()
    for u in raw["users"]:
        _require(isinstance(u, dict) and _is_str(u.get("id"), 64, 1) and _is_str(u.get("email"))
                 and _is_str(u.get("display_name")) and _is_str(u.get("password_hash")), "user")
        _require(u["id"] not in state.users and email_key(u["email"]) not in state.emails,
                 "duplicate user")
        state.add_user(User(u["id"], u["email"], u["display_name"], u["password_hash"]))
    for t in raw["tokens"]:
        _require(isinstance(t, dict) and _is_str(t.get("token_sha256"), min_len=1)
                 and t.get("user_id") in state.users, "token")
        state.tokens[t["token_sha256"]] = t["user_id"]
    dossier_ids = set()
    for d in raw["dossiers"]:
        _require(isinstance(d, dict) and _is_str(d.get("dossier_id"), 64, 1)
                 and _is_str(d.get("domain"), min_len=1) and d.get("state") in ("ready", "failed")
                 and (d.get("researched_at") is None or _is_str(d.get("researched_at")))
                 and _is_int(d.get("spent_units")) and d["spent_units"] >= 0
                 and isinstance(d.get("fields"), dict) and set(d["fields"]) == set(FIELDS)
                 and all(_valid_field(n, v) for n, v in d["fields"].items()), "dossier")
        _require(d["dossier_id"] not in dossier_ids and d["domain"] not in state.dossiers
                 and d["dossier_id"] not in state.users, "duplicate dossier")
        dossier_ids.add(d["dossier_id"])
        state.dossiers[d["domain"]] = Dossier(d["dossier_id"], d["domain"], d["state"],
                                              d["fields"], d["researched_at"], d["spent_units"])
    for r in raw["idempotency"]:
        _require(isinstance(r, dict) and r.get("user_id") in state.users
                 and _is_str(r.get("method"), min_len=1) and _is_str(r.get("path"))
                 and _is_str(r.get("key"), 255, 1) and _is_str(r.get("fingerprint"))
                 and _is_int(r.get("status")) and isinstance(r.get("body"), dict),
                 "idempotency record")
        state.idempotency[(r["user_id"], r["method"], r["path"], r["key"])] = IdempotencyRecord(
            r["fingerprint"], r["status"], r["body"])
    return state
