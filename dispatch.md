# The dispatch

The only human message in the judged room, sent to Lead (mention) as one message. Seats were told nothing else.

```text
You are the lead seat for our factory. Build all four stages of the
dossier track, coordinating the other seats and keeping every stage in its own complete,
buildable folder. This message is the only human input for the whole run: do not ask me
anything and do not wait for me. Record any blocker and its evidence in your report.

Workspace root: /Users/manas.choudhary/band-buildathon
Working folder (read-only, specs and harness): /Users/manas.choudhary/band-buildathon/sf-buildathon-2026
Track: dossier (each stage is a "phase" in the seat mandates)
Result repository: /Users/manas.choudhary/band-buildathon/band-work/result
Branch: main (shared; every seat commits here; no other branches)
Plans directory: <result>/plans/ (one matrix file and one plan file per stage)
Acceptance tests directory: <result>/acceptance/stage-N/ (owned by the Plan Checker;
the Builder may not edit or read it)
Check output directory: /Users/manas.choudhary/band-buildathon/band-work/checks/

Spec files, one per stage. Open each only when its stage starts:
1. /Users/manas.choudhary/band-buildathon/sf-buildathon-2026/challenges/dossier/spec/stage-1.md
2. /Users/manas.choudhary/band-buildathon/sf-buildathon-2026/challenges/dossier/spec/stage-2.md
3. /Users/manas.choudhary/band-buildathon/sf-buildathon-2026/challenges/dossier/spec/stage-3.md
4. /Users/manas.choudhary/band-buildathon/sf-buildathon-2026/challenges/dossier/spec/stage-4.md

Stage N is implemented in <result>/stage-N/. Stage 1 starts empty. For stage N > 1, first
copy the final stage-(N-1)/ to stage-N/ (no .git inside it), commit the copy, then extend
the copy using spec stage-N.md. Do not open a later spec until the stage before it is
final, and do not change a stage folder once the next spec is open. Each stage folder
must have its own Dockerfile, RUN.md and complete source, and must build and serve from a
clean container by following its RUN.md. Never commit credentials; read provider keys
only from the environment.

Paste the complete spec text for the current stage into every brief you send. Build to
the spec, not to the tests: the supplied tests are a small part of what is judged, so
every requirement in the spec counts, including ones no supplied test exercises.

Checks. Run from the working folder with its virtual environment. One check run at a
time on this machine. Every run uses a new --out directory (an existing one is refused);
name it by stage, seat and attempt, e.g. s1-cr-03.

  While iterating (host mode):
  .venv/bin/python -m harness run --track dossier \
    --repo /Users/manas.choudhary/band-buildathon/band-work/result --stage N \
    --out /Users/manas.choudhary/band-buildathon/band-work/checks/sN-<seat>-<NN>

  Final check of each stage, run by the Verifier on the commit it accepts:
  .venv/bin/python -m harness run --track dossier \
    --repo /Users/manas.choudhary/band-buildathon/band-work/result --stage N \
    --mode isolated \
    --out /Users/manas.choudhary/band-buildathon/band-work/checks/sN-final-<NN>

A stage is done only when its final isolated run prints `claimed stage: N`. The run also
tries the next stage's suite: for stages 1 to 3 that line should fail. If stage-N/ passes
the next stage's suite entirely, it claims nothing; that is a bad result, not a bonus.
Read report.json and the per-stage logs for failures and fix the implementation, never
the checks. `claimed stage: none` or a startup error is a failed stage.

How the result is judged, beyond the checks: the stage-2 screens must be coherent,
responsive and clear in every state the spec names; stage 4's research spend per correct
field is compared with a fixed benchmark, so spend research units only where they change
a field. Code must stay maintainable by another developer.

Do not edit anything under the working folder. Do not push. Do not create other
repositories.

Save wall-clock time: run independent work in parallel (acceptance tests are written
while the implementation proceeds; the next folder copy can happen while a plan is
written). Do not repeat work another seat has already verified.

After each stage, post the stage report: outcome, accepted full commit hash, the final
check's result lines, wall time from this dispatch, rejections that changed the work, and
open risks. After stage 4, or at the first stage that cannot be completed, post the run
report and stop.
```
