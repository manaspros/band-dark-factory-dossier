# Band Dark Factory: Dossier

**The problem.** Agents write code fast, but a person still reads every diff and steers
every run, so the person is the bottleneck. This entry is a five-seat software factory in
Band Desktop that finished all four Dossier stages from **one human message**, with no
context lost between seats and with every stage accepted by an independent verifier on a
different model family, not by a human reading the code.

- **Track:** Dossier (BAND Dark Factory Buildathon, San Francisco & Remote, Nov 2026).
- **Team:** GitHub `manaspros` (solo).
- **Result of the judged run:** stages 1-4 each claim their stage in the Verifier's final
  isolated harness run (`claimed stage: 4`, suites 122/122, 12/12, 9/9, 10/10 on
  `stage-4/`). 63 commits by four seats; delivery time 9 h 17 min, of which about 2 h 37 min
  was the laptop asleep (disclosed in `FACTORY.md`).

## How to read this repository

| Path | What it is |
|---|---|
| `FACTORY.md` | The factory: problem, five laws, seats, setup to reproduce, workflow, design choices and costs, measured time and spend, how it caught bad work, what failed. Start here. |
| `mandates/` | One mandate per seat (`lead`, `planner`, `plan-checker`, `builder`, `verifier`), each starting with its harness, model and effort. Generic: no track vocabulary. |
| `factory-bin/` | The launchers each seat's Band runtime runs: clean config home, per-seat Git identity, no commit signing. No secrets. |
| `dispatch.md` | The single human message of the judged run. |
| `room.json` | The full Band session of the judged room "Dossier Run", downloaded from the Band console, unedited. |
| `stage-1/` ... `stage-4/` | One complete, buildable service per stage (`Dockerfile`, `RUN.md`, source), each the previous one carried forward and widened. Written by the band only. |
| `plans/` | Per-stage requirement matrices, implementation plans and builder notes, committed by the seats. |
| `acceptance/` | The Plan Checker's holdout acceptance tests per stage, written from the spec without seeing the code. |
| `dossier-runway.com.json` | `GET /dossiers/runway.com` from `stage-4/` built against the live web with our own Nimble key, saved verbatim. |

## Run it

```sh
cd stage-4
docker build -t dossier-stage-4 . && docker run --name dossier -p 8080:8080 -e PORT=8080 \
  -e NIMBLE_API_KEY dossier-stage-4
# open http://localhost:8080/ , sign up, research a domain
```

Full instructions per stage are in each `stage-N/RUN.md`.

## Honest notes

- One operator action happened during the judged run: after the laptop slept with the lid
  closed, Planner's turn died, and the operator restarted Planner's Band runtime. No
  message, hint or approval entered the room. Details and timestamps in `FACTORY.md`.
- The live `runway.com` dossier is `ready` with CEO, CTO and investors known, but the legal
  name is unknown and headcount and total funding are contested and implausible. It is
  committed unedited.
- Open risks the band itself recorded: T38 (import does not cross-check a candidate's
  start date against its page version), deviations DEV-S1, DEV-S2, DEV-S3a, DEV-S3b, and
  no early stop in research, so research economy was not measured.
- `README.md` and `FACTORY.md` were written by the human after the run, from the room log
  and the Git history.
