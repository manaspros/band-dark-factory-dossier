"""`/_test/export` and `/_test/import` state (§10, stage-3 "Upgrades").

A stage-3 export holds, besides the stage-1 parts, each dossier's builds and history and
the change feed. Import accepts that shape, and the exports of this team's stage-1 and
stage-2 services (dossiers without `builds`, no `feed`), which app.migrate upgrades. Import validates the whole
payload first and builds a new ``State``; anything invalid is 422 with nothing changed.
"""
from __future__ import annotations

from app import restore
from app.domains import is_valid as is_valid_domain
from app.errors import invalid
from app.migrate import import_field, is_rfc3339, same_page_dates, upgrade_dossier, valid_field
from app.store import BuildRecord, Dossier, IdempotencyRecord, State, User, email_key
from app.support import FIELDS

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
    _require(_common_dossier(d) and set(d) == STAGE3_DOSSIER_KEYS
             and restore.valid_fields(d["fields"], d["domain"])
             and restore.valid_dossier_times(d)
             and restore.valid_history(d["history"], d["domain"]), "dossier")
    builds = [BuildRecord.from_json(b) for b in d["builds"]]
    _require(restore.derived_entries(builds)[0] == d["history"], "history")
    return Dossier(d["dossier_id"], d["domain"], d["state"], d["fields"], d["researched_at"],
                   d["spent_units"], builds, d["history"])


def _earlier_dossier(d) -> Dossier:
    """A dossier of a stage-1 or stage-2 export, as stage 3 keeps it."""
    _require(_common_dossier(d)
             and isinstance(d.get("fields"), dict) and set(d["fields"]) == set(FIELDS)
             and all(valid_field(n, v, d["domain"]) for n, v in d["fields"].items())
             and (d["researched_at"] is not None
                  or all(v["value"] is None for v in d["fields"].values())), "dossier")
    fields = {name: import_field(name, value, d["researched_at"])
              for name, value in d["fields"].items()}
    _require(same_page_dates(fields), "dossier")
    fields, builds, history = upgrade_dossier(fields, d["researched_at"], d["spent_units"])
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
    for dossier in state.dossiers.values():   # each dossier's feed: what its builds added
        _require(restore.feed_of(state.feed, dossier.domain)
                 == restore.derived_entries(dossier.builds)[1], "feed")
    for r in raw["idempotency"]:
        _require(isinstance(r, dict) and _is_user(state, r.get("user_id"))
                 and _is_str(r.get("method"), min_len=1) and _is_str(r.get("path"))
                 and _is_str(r.get("key"), 255, 1) and _is_str(r.get("fingerprint"))
                 and _is_int(r.get("status")) and isinstance(r.get("body"), dict),
                 "idempotency record")
        state.idempotency[(r["user_id"], r["method"], r["path"], r["key"])] = IdempotencyRecord(
            r["fingerprint"], r["status"], r["body"])
    return state
