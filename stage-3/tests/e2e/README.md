# Browser checks (run by hand)

Two Playwright scripts that drive the built image against the harness mock web. They need a
Playwright Chromium, so they run inside the harness runner image; neither is part of pytest.

```sh
docker network create dossier-e2e
docker run --rm -d --name web --network dossier-e2e -e MOCK_ADMIN_TOKEN=local-admin \
  -v "$PWD/<working folder>/challenges/dossier/web/corpus/sample:/data/corpus:ro" <mock image>
docker run --rm -d --name svc --network dossier-e2e -e PORT=8000 -e NIMBLE_API_KEY=local \
  -e NIMBLE_BASE_URL=http://web:8080/nimble dossier-stage-2
docker run --rm --network dossier-e2e -v "$PWD/tests/e2e:/work" --entrypoint python3 \
  df-harness-runner:latest -I /work/screens_walk.py http://svc:8000 /work
docker run --rm --network dossier-e2e -v "$PWD/tests/e2e:/work" --entrypoint python3 \
  df-harness-runner:latest -I /work/behaviour.py http://svc:8000 http://web:8080
```

- `screens_walk.py`: signs up, researches, opens every route at 375 px and 1280 px, checks
  for horizontal scrolling and unlabelled inputs, and writes screenshots.
- `behaviour.py`: a lost research response and a lost refresh response, each shown as
  uncertain and retried with the same `Idempotency-Key`; latest read wins against a delayed
  stale response; polling while building. Run it against a fresh service: on a second run the
  dossier already exists, so "one build" counts zero builds.
