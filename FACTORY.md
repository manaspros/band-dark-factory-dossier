# FACTORY.md: a five-seat dark factory in Band Desktop

## The problem this factory solves

Agents write code fast, but a person still reads every diff and steers every run, so the
person is the bottleneck. This factory lets agents finish real work with **no human after
the dispatch**, **no context lost between seats**, and results **trusted without a human
reading every line**.

It rests on five laws:

1. **The slowest trusted check caps throughput.** One full check at a time, run only by the
   seat holding the work item; the expensive isolated check runs on the commit being
   accepted, not on every iteration.
2. **Every untyped handoff loses context.** Every handoff is an eight-part typed brief with
   the requirements pasted in full. A message id, a task id or "read the room" is never a
   handoff.
3. **Parallelism only shortens the critical path.** Acceptance tests are written while the
   code is written; the next folder is copied while the plan is written.
4. **Agents optimise the check they can see.** The requirements become a matrix of verbatim
   quotes; an independent seat writes holdout acceptance tests the builder never sees; both
   reviewers run on a different model family from the authors.
5. **Human attention is the scarcest resource.** One dispatch, then nothing: seats decide,
   or record a blocker as the outcome.

## Result of the judged run

| Stage | Accepted revision | Verifier's final isolated check | Time from dispatch |
|---|---|---|---|
| 1 | `11357750` | `s1-final-03`: suite 1 pass, claimed stage 1 | 2 h 23 min |
| 2 | `f50cd1c3` | `s2-final-04`: suites 1-2 pass, claimed stage 2 | 3 h 49 min |
| 3 | `5bacfdba` | `s3-final-02`: suites 1-3 pass, claimed stage 3 | 4 h 53 min |
| 4 | `0d9546ba` | `s4-final-02`: suites 1-4 pass (122/122, 12/12, 9/9, 10/10), claimed stage 4 | 9 h 20 min (about 2 h 37 min of it the laptop asleep, see below) |

One human message (the dispatch, `dispatch.md`), 63 commits by four seats (Builder 30,
Planner 23, Plan Checker 9, Lead 1; the Verifier never commits by design).

## Seats

| Seat | Harness | Model | Effort | Owns | Never does |
|---|---|---|---|---|---|
| Lead | Claude Code | claude-sonnet-5-5 | medium | the task, typed briefs, phase gates, rulings after two review cycles, phase reports | plan, code, tests, review |
| Planner | Claude Code | claude-opus-5-5 | high | requirement matrix (one row per normative sentence, verbatim quote, how verified) and implementation plan | code |
| Plan Checker | Codex | gpt-6-luna | medium | audits the matrix line by line against the requirements; then writes holdout acceptance tests from the requirements only | review code |
| Builder | Claude Code | claude-opus-5-5 | high | the implementation, test-first, committed as it goes | edit or read the acceptance tests or supplied checks |
| Verifier | Codex | gpt-6-luna | medium | checks out the exact revision, runs the supplied checks and the holdout tests itself, reads requirements against code, accepts one full commit hash after an isolated run | fix code |

Two model families on purpose: the authors (Planner, Builder) are Claude; the reviewers
(Plan Checker, Verifier) are GPT. A reviewer from the author's family tends to share its
blind spots. Lead is Claude because coordination needs no cross-family check and it carries
the most traffic (see "What failed").

The mandates are in `mandates/`; each starts with its `Harness:`, `Model:` and `Effort:`
lines. They name no track, endpoint, field or error code: to point the factory at a
different problem, change only the dispatch.

## Setup (to reproduce)

1. **Seats.** Band Desktop, five **New local agent** seats in host mode, working directory =
   your workspace root (the folder holding the specs checkout and the result repository),
   handles `lead`, `planner`, `plan-checker`, `builder`, `verifier`.
2. **Mandates.** Set each seat's instructions to `mandates/<seat>.md`. We used
   `band agent instructions set --as <owner>/<seat> --instructions-file mandates/<seat>.md`,
   which live-links the file so an edit reaches the seat on its next wake.
3. **Runtime per seat.** Harness, model and effort as in the table. Approvals: Claude Code
   seats "auto"; Codex seats "never ask, full access". MCP servers: "only Band's".
4. **Clean config homes.** Each seat's Runtime "Command" is its launcher from
   `factory-bin/`. The launcher points the harness at its own config home
   (`CLAUDE_CONFIG_DIR=~/.claude-band` or `CODEX_HOME=~/.codex-band`, each logged in once,
   with no personal memories, instructions or MCP servers), sets a per-seat Git author and
   committer, turns off commit signing, and adds the usual per-user bin folders to `PATH`
   (a GUI app does not inherit the shell's). Why: in a rehearsal the coordinator loaded the
   operator's personal agent memory and briefed a seat about it.
5. **Smoke test.** In a scratch room, ask Lead to run `git var GIT_AUTHOR_IDENT` and to have
   Verifier do the same. Both should answer with their seat names, which proves the launcher
   ran and the mentions resolve.
6. **Run.** A fresh empty result repository (`git init -b main`) and a fresh room with
   exactly the five seats. Send the dispatch as one message mentioning only Lead (we used
   `band room send <room> "<dispatch>" --mention <lead-id>`; pasting it once into the
   composer after picking Lead's mention chip also works). Send nothing after it.
7. **Power.** Keep the machine awake and on AC power for the whole run
   (`caffeinate -dimsu`). A sleeping laptop pauses every seat, and a seat whose turn dies
   while the machine sleeps does not resume on its own.

## The workflow, per phase

```
dispatch ──> Lead
  Lead ─brief─> Planner: matrix + plan           Lead ─brief─> Builder: copy the previous folder, commit
  Planner <─audit, up to 2 cycles─> Plan Checker       (rows the supplied checks never exercise are marked)
  open points after 2 cycles ─> Lead rules
  Lead ─brief─> Builder: implement   ║ in parallel ║   Lead ─brief─> Plan Checker: holdout acceptance tests
  Builder ─full commit hash, files, commands with exit statuses─> Verifier, Lead
  Verifier <─reject with row IDs + reproduction, up to 2 cycles─> Builder
  open gaps after 2 cycles ─> Lead rules (final for the phase)
  Verifier: isolated final check on the exact commit ─ACCEPT <hash>─> Lead ─phase report─> room
```

Every brief has eight numbered parts: goal, requirements (verbatim, split into numbered
messages with a "final part" marker when long), constraints with their source, scope
(paths the seat may and may not touch), repository and base commit, checks, budget, and the
inputs from other seats as full hashes. A seat that receives a brief with a part missing
asks Lead for it rather than reconstructing it.

The room shows the work was shared: of 318 seat-to-seat messages (counted by mention),
Lead sent 141 briefs and rulings, the other seats sent 104 reports to Lead, and 73 went
directly between them (Plan Checker ↔ Planner 33, Verifier ↔ Builder 20, Plan Checker ↔
Verifier 20). Tool calls: Builder 459,
Plan Checker 424, Verifier 421, Planner 306, Lead 160.

## Design choices, reasons, and what they cost

| Choice | Reason | Cost | Rejected alternative |
|---|---|---|---|
| Requirement matrix with verbatim quotes; rows the supplied checks miss are marked | the supplied checks are a small share of what is judged; the matrix makes unchecked requirements visible | a planning step before any code (about 25 min in stage 1) | build straight from the spec |
| Holdout acceptance tests by a seat that never sees the code | a builder optimises the checks it can see | one more seat writing tests | builder writes all tests |
| Reviewers on a different model family | same-family reviewers share blind spots | two harnesses to set up and pay for | one model for everything |
| Two review cycles, then the coordinator rules | prevents author/reviewer loops in a run nobody may steer | a ruling can accept a known gap (recorded as an open risk) | unlimited cycles |
| One shared `main`, commits as you go | the room's trail and the Git history line up | seats must not touch each other's paths | branch per work item (Band's built-in Delivery team does this) |
| Only the Verifier's isolated run accepts a phase | isolated mode is how judging runs; host mode hides network dependence | about 1 min per isolated run | accept on the builder's host-mode pass |
| A frozen folder stays frozen | the next spec is open, so changing an earlier folder breaks the stage history | a gap found late becomes a documented deviation | patch earlier folders |
| Clean config homes via launchers | personal memories leaked into a rehearsal room | one login per home | default config |

Kept from Band's built-in Delivery team: never claim a check passed without running it;
never pipe a gate through a filter; smallest complete change; cite file and line; every
finding needs a demonstration. Removed: "ask the user" (dark factory), per-ticket branches,
and "the user decides" at the end of the work.

## Measured time and spend (judged run)

- **Delivery time** (first to last seat message in `room.json`): 05:37:27 to 14:54:36 UTC,
  **9 h 17 min**. That includes about 2 h 37 min when the laptop was asleep and no seat ran
  (see "What failed"); active time is about 6 h 40 min.
- **Tokens**, read from the seats' own session logs after the dispatch:
  - Planner + Builder (claude-opus-5-5): 0.81 M output, 179 M cache-read, 2.7 M cache-write
    input tokens.
  - Lead (claude-sonnet-5-5): 0.11 M output, 54 M cache-read, 0.81 M cache-write.
  - Plan Checker + Verifier (gpt-6-luna): 147.6 M tokens, of which 143.4 M cached input,
    0.60 M output (0.37 M of it reasoning).
- **Spend.** At Anthropic list prices the Claude seats come to about **$74** (Opus about
  $66, Sonnet about $8.5). The seats ran on subscription logins (a Claude plan and a
  ChatGPT Plus plan), so the marginal cost was the plans; the GPT seats used 8% of one
  5-hour Plus window and 1% of the weekly one.
- **Research economy** was not measured: Lead's report records that every build runs a
  25-unit research pass with no early stop, and the harness economy figure is null on the
  shipped checks.

## How the factory catches and recovers from bad work (from this run's room)

- **Plan audit, stage 1.** At 05:51 UTC Plan Checker blocked the first matrix (`9900ebd`):
  normative sentences of the spec had no row, and a row misread how header names are
  recognised. Planner fixed it over two cycles (`560be0b`, `4e50d5e`, `9ac3a92`), and Lead
  ruled on the three points still open (`910ca63`).
- **Verifier rejection, stage 1.** At 07:02 UTC Verifier ran the isolated harness (stage 1
  pass, 122/122) and still rejected revision `f1b357c` with three reproduced defects the
  shipped checks never asked about: a 5,000-digit `limit` query returned 500 instead of
  422 (row R87); an import with an unhashable user id returned 500 (R167); a timestamp
  without seconds was accepted as RFC 3339 (R38). Builder fixed them in `e1da145`, then a
  headquarters-city extraction bug in `1135775`, which Verifier accepted after its isolated
  run.
- **Verifier rejection, stage 2.** Verifier showed that an import with
  `headcount_range = "banana"` returned 204 and stored the value, and that research polls
  did not honour rate limits. Builder fixed both (`131dc99`), Verifier withheld acceptance
  once more for an import path that could still return 500 (`da04be0`) and for imported
  values not supported by their excerpts (`f50cd1c`), then accepted.
- **Coordinator catch, stage 3.** Before Verifier's verdict, Lead sent an import
  inconsistency (T38) back to Builder. The messages crossed: Verifier accepted the earlier
  revision with T38 recorded as an open risk, so Builder reverted its late fix to keep the
  accepted folder byte-identical (`0ffd736`), and the risk is listed in Lead's report.
- **Plan audit, stage 4.** Plan Checker found an arithmetic error in the plan's time bound;
  Planner agreed ("You were right about the arithmetic") and rebased the bound on an 8 s
  guard (`7a30e10`).
- **The holdout tests are reviewed too.** Verifier found assertion defects in Plan
  Checker's own acceptance tests in stages 2, 3 and 4; Plan Checker fixed them
  (`99c60f1`, `5bacfdb`, `ecf3d34`).
- **Frozen folders.** Gaps found after a later spec was open were recorded as documented
  deviations (DEV-S1, DEV-S2, DEV-S3a, DEV-S3b), never edited back into an earlier folder.

## What failed and what we learned

- **Docker Sandbox seats.** Blocked by a Docker MCP version mismatch; seats run on the host.
- **macOS privacy prompts.** A workspace under `~/Downloads` triggered folder-access
  prompts for every seat, so the workspace moved out of it.
- **GUI dispatch.** Typing a long dispatch into the composer submitted on a newline and
  garbled the first rehearsal. Dispatches are now sent as one message.
- **Personal memory leak.** In rehearsal 2 the coordinator loaded the operator's personal
  agent memory and briefed a seat about it. Fixed with clean config homes (setup step 4).
- **Quota.** Three Codex seats on a ChatGPT Plus plan used the whole 5-hour window in 36
  minutes of rehearsal (the coordinator alone carried 31% of the room's traffic). Lead moved
  to Claude; the reviewers moved to a cheaper GPT model and used 8% of a window in the
  judged run.
- **Unresolved mentions.** After the switch to Claude, Lead wrote a bare `@verifier`, which
  Band left as plain text and nobody was woken. All mandates now say to use the handle
  exactly as the participant list shows it.
- **Laptop sleep, and one disclosed operator action.** The machine slept twice: about 17
  minutes in stage 1 (12:00-12:17 IST; Builder recovered by itself), and from 16:00 to
  18:20 IST at the start of stage 4 ("Entering Sleep state due to 'Clamshell Sleep'", lid
  closed on battery; `caffeinate` does not prevent lid sleep on battery). In the second
  sleep Planner's turn died mid-response ("API Error: Your computer went to sleep
  mid-response", 17:17 IST) while it wrote the stage-4 matrix; Lead recorded "Stage 4 is
  waiting on the planner" and went idle, so the band stalled. At 18:52 IST (13:22:40 UTC)
  the operator restarted only Planner's Band runtime for this room
  (`band restart --as <owner>/planner --host-session planner-<room-id>`). Band re-delivered
  the five queued, unacknowledged brief messages; Planner resumed from them. No message,
  hint or approval entered the room. Fixes: run on AC power with `caffeinate -dimsu`
  (setup step 7); and a lesson for the Lead mandate, not applied during the run: a
  coordinator should re-brief a seat whose turn ended in an error instead of waiting.
- **Live data quality.** The live `runway.com` build (`dossier-runway.com.json`, stage 4) is
  `ready` with CEO, CTO and investors known, but `legal_name` unknown and
  `headcount_range` (10001+) and `funding_total` (2,000,000) contested and implausible. The
  shipped checks run against a mock web; the band had no live-web feedback during the run.
  The file is committed unedited.
