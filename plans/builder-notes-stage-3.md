# Builder notes — stage 3 carry-forward

Base: stage-2 final f50cd1c. `stage-3/` is a byte-identical copy of the committed `stage-2/`
tree (commit 101ec98, copy only). Spec: `challenges/dossier/spec/stage-3.md` in the working
folder (Upgrades, Restarts).

## 1. What a stage-2 export records (stage-2/app/store.py `export_state`)

Per dossier, only:

| Key | Meaning in stage 2 |
|---|---|
| `dossier_id`, `domain` | identity |
| `state` | outcome of the **last** completed build (`ready` or `failed`) |
| `researched_at` | time of the last build that completed `ready` (null if none) |
| `spent_units` | **total** units of every finished build, one number |
| `fields` | the six fields of the last `ready` build: value, status, citations, candidates (value, url, excerpt, provider, kind, published_at, retrieved_at, selected) |

Also users, token hashes and idempotency records (unchanged from stage 1). There is no
clock, no build list, no page list, no `Effective` value, no history and no feed.

## 2. Gaps against stage-3 Upgrades

U1. **No build list.** Upgrades: "State imported from a stage-2 export keeps the builds that
the stage-2 service made, each with its time, its outcome and its spending." The export
holds none of this. Stage 2 overwrote `fields` on each ready build and kept a running total
of `spent_units`. Earlier builds' times, outcomes, per-build spending and candidates are not
recoverable. Only these are recorded: the last ready build's time (`researched_at`) and
candidates, and whether the last build failed (`state`).
*Proposal:* treat a stage-2 dossier the way Upgrades treats a stage-1 one:
- one build that completed `ready` at `researched_at`, holding all exported candidates;
- the whole `spent_units` charged to that build;
- a dossier whose `researched_at` is null has no ready build, so every `as_of` gives 404;
- the exported `state` stays the dossier's current outcome.

Consequences:
- an `as_of` before `researched_at` gives 404 even if stage 2 had earlier ready builds;
- `spent_units` at `as_of` counts later failed builds at `researched_at`.

This needs a lead ruling as a documented limitation.

U2. **No `Effective` header.** Stage 2 never parsed `Effective:`, so the export cannot give a
page's `true_from` when the page had that line. It records only `published_at` per
candidate, which is the fallback in "Two times per value".
*Proposal:* for an imported stage-2 candidate:
- `true_from` = UTC date of `published_at`, or null when `published_at` is null;
- for a candidate stage 2 had itself imported (null `kind`), `published_at` is null, so `true_from` is null.

This is wrong exactly when the page had a valid `Effective` line. Needs a ruling.
The same choice decides the `initial` history entry's `true_from`. Upgrades says "true_from
null unless the exported state records the dates that give it", and `published_at` is such a
date when no `Effective` line existed. The alternative is to always use null for stage-2
imports.

U3. **Pages with no candidates are not recorded.** A stage-3 page version "with no
candidates still replaces or ends earlier versions". Stage 2 kept only candidates, so URLs
it read without finding a value are lost. With one reconstructed build (U1) nothing is
earlier for them to replace, so this has no effect on `/values` at import. It is noted for
completeness.

U4. **`learned_at` of imported candidates.** It should be "the first build that gathered" the
same field/value/URL/provider. A stage-2 candidate records only `retrieved_at`, the build that
gathered it into the current set. With U1 this is `researched_at` and is used as `learned_at`,
the same rule Upgrades gives for stage-1 imports. Earlier first-gathering times are lost (part
of U1).

U5. **Imported-by-stage-2 state.** "State that the stage-2 service had itself imported counts
as one build ... at researched_at." This is consistent with U1. Such candidates are
recognisable by `kind: null`. No gap.

U6. **`executives`.** Neither export shape has it. After import it is `unknown` with no
history entry, as the spec says. No gap.

U7. **Idempotency bodies.** Stored responses from stage 1 and 2 hold dossier views without
`true_from`, `learned_at` or `executives`. A replay returns the stored body as §7 and §10
require. Expected, not a gap.

The stage-1 export and its fixture are unaffected. Upgrades already defines them as one build
at `researched_at` with `learned_at = retrieved_at`.

## 3. Persistence today, against stage-3 Restarts

R1. **Memory only.** `app.store.Store` keeps `State` in a Python object, and nothing is
written to disk. A restart loses every user, token, dossier, idempotency record and the clock.

R2. **The clock is in memory** (`app.clock.Clock._now`). Restarts require the same time after a
restart, so every `POST /_test/clock` and reset must be persisted.

R3. **Nothing per build is recorded.** Stage 3 needs these, all durable:
- per dossier, a build log: time, outcome, spending, and for ready builds the page versions (URL, `true_from`, candidates, including pages with no candidates);
- history entries;
- a global feed with a monotonic `seq` that never reuses a number after a restart.

R4. **The Dockerfile runs as user `dossier`, with no writable directory.** `/srv` is
root-owned. A durable store needs a data directory the user owns, for example
`/srv/data` created and chowned in the image. The container filesystem persists across
restarts, so no volume is needed. RUN.md must say where state lives.

R5. **Commit point.** Today every mutation happens in one synchronous section on the event
loop. A durable store can keep that model, provided each request's change is written and
fsynced in the same section before the response is sent. A build's commit (`Builds._commit`)
is also such a section. SQLite (stdlib, no new dependency) in WAL mode with
`synchronous=FULL`, one transaction per state change, satisfies the lead's note.

## 4. Checks run on the copy (101ec98)

- `cd stage-3 && /tmp/builder-venv/bin/python -m pytest -q -p no:cacheprovider tests` gave exit 0: "311 passed".
- `cd stage-3 && docker build -q -t dossier-s3-copy:builder .` gave exit 0.
