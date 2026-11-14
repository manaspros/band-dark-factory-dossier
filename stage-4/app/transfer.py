"""`/_test/export` and `/_test/import` state (§10, stage-3 "Upgrades").

A stage-4 export holds, besides the stage-1 parts, each dossier's builds and history, the
change feed and the batches. Import accepts that shape, the stage-3 shape (no `investors`,
no origins) and the exports of this team's stage-1 and stage-2 services (dossiers without
`builds`, no `feed`), which app.migrate upgrades. Builds in flight are not exported: an
export holds each dossier as its last completed build left it. Import validates the whole
payload first and builds a new ``State``; anything invalid is 422 with nothing changed.
"""
from __future__ import annotations

from app import restore
from app.domains import is_valid as is_valid_domain
from app.errors import invalid
from app.migrate import (import_field, is_rfc3339, upgrade_dossier, upgrade_to_stage4,
                         valid_field)
from app.store import Batch, BuildRecord, Dossier, IdempotencyRecord, State, User, email_key
from app.support import FIELDS

MAX_BATCH_DOMAINS = 50
MAX_BATCH_BUDGET = 100000
BATCH_KEYS = {"batch_id", "user_id", "budget_units", "domains", "started", "spent_units"}

TRACK = "dossier"
FORMAT_VERSION = 1
STAGE3_DOSSIER_KEYS = {"dossier_id", "domain", "state", "fields", "researched_at",
                       "spent_units", "builds", "history"}


def export_state(state: State) -> dict:
    """A JSON snapshot: committed dossiers only, never a running build's partial work."""
    return {
        "users": [{"id": u.id, "email": u.email, "display_name": u.display_name,
                   "password_hash": u.password_hash} for u in state.users.values()],
        "tokens": [{"token_sha256": t, "user_id": uid} for t, uid in state.tokens.items()],
        "dossiers": [{"dossier_id": d.id, "domain": d.domain, "state": d.outcome,
                      "fields": d.fields, "researched_at": d.researched_at,
                      "spent_units": d.spent_units,
                      "builds": [b.as_json() for b in d.builds], "history": d.history}
                     for d in state.dossiers.values()],
        "idempotency": [{"user_id": k[0], "method": k[1], "path": k[2], "key": k[3],
                         "fingerprint": r.fingerprint, "status": r.status, "body": r.body}
                        for k, r in state.idempotency.items()],
        "feed": state.feed,
        "batches": [b.as_json() for b in state.batches.values()],
    }


def _require(condition: bool, what: str) -> None:
    if not condition:
        raise invalid(f"invalid state: {what}")


def _is_str(value, max_len: int | None = None, min_len: int = 0) -> bool:
    return isinstance(value, str) and len(value) >= min_len and (
        max_len is None or len(value) <= max_len)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_user(state: State, value) -> bool:
    return isinstance(value, str) and value in state.users


def _common_dossier(d) -> bool:
    """The parts every export shape shares."""
    return (isinstance(d, dict) and _is_str(d.get("dossier_id"), 64, 1)
            and _is_str(d.get("domain")) and is_valid_domain(d["domain"])
            and _is_str(d.get("state")) and d["state"] in ("ready", "failed")
            and is_rfc3339(d.get("researched_at"), nullable=True)
            and _is_int(d.get("spent_units")) and d["spent_units"] >= 0)


def _stage3_dossier(d) -> Dossier:
    """A dossier of a stage-3 or stage-4 export (both keep builds), in stage 4."""
    shape = restore.shape_of(d)
    _require(_common_dossier(d) and set(d) == STAGE3_DOSSIER_KEYS
             and restore.valid_fields(d["fields"], d["domain"], shape)
             and restore.valid_dossier_times(d, shape)
             and restore.valid_history(d["history"], d["domain"], shape), "dossier")
    fields, builds, history = d["fields"], d["builds"], d["history"]
    if not shape.stage4:
        fields, builds, history = upgrade_to_stage4(builds, history)
    return Dossier(d["dossier_id"], d["domain"], d["state"], fields, d["researched_at"],
                   d["spent_units"], [BuildRecord.from_json(b) for b in builds], history)


def _earlier_dossier(d) -> Dossier:
    """A dossier of a stage-1 or stage-2 export, as stage 3 keeps it."""
    _require(_common_dossier(d)
             and isinstance(d.get("fields"), dict) and set(d["fields"]) == set(FIELDS)
             and all(valid_field(n, v, d["domain"]) for n, v in d["fields"].items())
             and (d["researched_at"] is not None
                  or all(v["value"] is None for v in d["fields"].values())), "dossier")
    fields = {name: import_field(name, value, d["researched_at"])
              for name, value in d["fields"].items()}
    _, builds, history = upgrade_dossier(fields, d["researched_at"], d["spent_units"])
    fields, builds, history = upgrade_to_stage4(builds, history)
    return Dossier(d["dossier_id"], d["domain"], d["state"], fields, d["researched_at"],
                   d["spent_units"], [BuildRecord.from_json(b) for b in builds], history)


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
                 and _is_user(state, t.get("user_id")), "token")
        state.tokens[t["token_sha256"]] = t["user_id"]
    dossier_ids = set()
    for d in raw["dossiers"]:
        stage3 = isinstance(d, dict) and "builds" in d   # the shape is told per dossier
        dossier = _stage3_dossier(d) if stage3 else _earlier_dossier(d)
        _require(dossier.id not in dossier_ids and dossier.domain not in state.dossiers
                 and dossier.id not in state.users, "duplicate dossier")
        dossier_ids.add(dossier.id)
        state.dossiers[dossier.domain] = dossier
    if "feed" in raw:  # stage 3; earlier exports start with an empty feed
        _require(restore.valid_feed(raw["feed"], set(state.dossiers)), "feed")
        state.feed = raw["feed"]
    for r in raw["idempotency"]:
        _require(isinstance(r, dict) and _is_user(state, r.get("user_id"))
                 and _is_str(r.get("method"), min_len=1) and _is_str(r.get("path"))
                 and _is_str(r.get("key"), 255, 1) and _is_str(r.get("fingerprint"))
                 and _is_int(r.get("status")) and isinstance(r.get("body"), dict),
                 "idempotency record")
        state.idempotency[(r["user_id"], r["method"], r["path"], r["key"])] = IdempotencyRecord(
            r["fingerprint"], r["status"], r["body"])
    batches = raw.get("batches", [])   # earlier exports have none
    _require(isinstance(batches, list), "batches")
    for b in batches:
        _require(_valid_batch(state, b), "batch")
        state.batches[b["batch_id"]] = Batch.from_json(b)
    return state


def _valid_batch(state: State, b) -> bool:
    """A batch of an imported user over imported dossiers, its spending within its budget."""
    if not (isinstance(b, dict) and set(b) == BATCH_KEYS and _is_str(b["batch_id"], 64, 1)
            and b["batch_id"] not in state.batches and b["batch_id"] not in state.users
            and all(b["batch_id"] != d.id for d in state.dossiers.values())
            and _is_user(state, b["user_id"])
            and _is_int(b["budget_units"]) and 1 <= b["budget_units"] <= MAX_BATCH_BUDGET
            and _is_int(b["spent_units"]) and 0 <= b["spent_units"] <= b["budget_units"]
            and isinstance(b["domains"], list) and isinstance(b["started"], list)):
        return False
    domains, started = b["domains"], b["started"]
    return (1 <= len(domains) <= MAX_BATCH_DOMAINS
            and all(_is_str(x) and x in state.dossiers for x in domains + started)
            and len(set(domains)) == len(domains) and len(set(started)) == len(started)
            and set(started) <= set(domains))
