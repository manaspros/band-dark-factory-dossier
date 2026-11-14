# Builder notes — stage 2 carry-forward

`stage-2/` is an exact copy of `stage-1/` at 1135775 (commit 2922b93). No behaviour changed.

## What the stage-1 export records

Source: `stage-1/app/store.py` (`export_state`) and `stage-1/app/evidence.py` (`decide`).

```
{"track": "dossier", "format_version": 1,
 "state": {
   "users":       [{"id", "email", "display_name", "password_hash"}],   # scrypt$salt$hash
   "tokens":      [{"token_sha256", "user_id"}],                        # sha256 of the bearer token
   "dossiers":    [{"dossier_id", "domain", "state" ("ready"|"failed"), "researched_at",
                    "spent_units",
                    "fields": {<six fields>: {"value", "status" ("known"|"unknown"),
                                              "citations": [{"url", "excerpt", "provider"}]}}}],
   "idempotency": [{"user_id", "method", "path" (raw request path), "key",
                    "fingerprint", "status", "body"}]}}
```

It records **no page texts, no page kind and no publication time**. Per field it records only the
selected value and every distinct (url, excerpt) supporting that value, each with its provider.

## Gaps against "Existing clients after an upgrade"

1. **Losing values are not recorded (real gap).** The spec gives an imported field one candidate
   for every value that the served text of the last ready build supports, once per page. Stage-1's
   `decide` keeps only the chosen value's citations and drops every other supported value before
   anything is stored. A field whose stage-1 evidence supported two values therefore imports with
   one value: `known` where the spec expects `contested`, and missing the other candidates. This
   cannot be rebuilt from the export, and stage-1 is frozen. It needs a lead ruling; the residual
   risk applies only to fields that had conflicting evidence in stage 1.
2. **Page texts are not recorded.** Candidates can still be rebuilt from the exported citations:
   each excerpt is text a provider served for `url` and supports its value under Appendix A. Rebuild
   one candidate per (field, value, url), using the first exported excerpt for that page.
3. **`kind` and `published_at` are not recorded.** The spec allows null for both ("as the exported
   state records them or else null"); a null kind has `aggregator` authority. Because every imported
   candidate is null/null, the selection rule falls through to URL, then provider, then value.
4. **Things that carry over as they are:**
   - provider: recorded per citation;
   - `retrieved_at`: the dossier's `researched_at`;
   - dossiers whose last build never completed ready: exported as `failed` with every field unknown,
     so they import with no candidates.
5. **Requirements on the stage-2 implementation, so that stage-1 exports keep working:**
   - Keep token storage as sha256 of the bearer token, so a browser signed in before the upgrade
     stays signed in. If the UI keeps the token in a cookie, the cookie value must be the same
     bearer token.
   - Keep the idempotency record key as (user, method, raw path, key) and keep the fingerprints:
     canonical JSON of `{"domain": ...}` for POST, `{}` for refresh. Then a retry with the same key
     and body after import replays the original 202/200 body.
   - Stage-2 import must accept the stage-1 `state` shape: fields with exactly `value`, `status`
     and `citations`, and no candidates. Stage-1's import validator is strict (`_valid_field`
     requires those three keys exactly, and status `known`/`unknown`), so it must be widened in
     stage-2. If stage-2 exports a richer state (candidates, pages), it should keep
     `format_version: 1` or accept both shapes.
   - Value normalisation for "same value": strings compared after stripping surrounding
     whitespace. Stage-1 values are already stripped, because excerpts are collapsed.

## Checks run on the copy

- `diff -r stage-1 stage-2` (excluding caches): identical. No `.git` inside `stage-2/`.
- `pytest tests` in `stage-2/`: 210 passed.
- `docker build` of `stage-2/`, then `docker run -e PORT=8080 -p`: `/health` returned `{"status":"ok"}`.
- I did not run the harness with `--stage 2`. The copy has no stage-2 behaviour, so the stage-2
  suite would fail by design and the run would show nothing new.
