"""Load and timing check against a running container (run by hand, not by pytest).

    python tests/load_check.py http://localhost:8080 example-domain.test

Sends 50 concurrent mixed requests (signup, login, list, read, create) and checks that
none is 5xx and each answers within 5 s (§2 limits, §5). Then waits for the build of the
given domain and checks that it ends within 10 s. Needs only the standard library.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def call(base: str, method: str, path: str, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"content-type": "application/json", **(headers or {})})
    began = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    return status, time.monotonic() - began, json.loads(raw) if raw else None


def main(base: str, domain: str) -> int:
    call(base, "POST", "/_test/reset", {"now": "2026-03-01T09:00:00+00:00", "users": [
        {"id": "u_load", "email": "load@example.com", "password": "correct horse",
         "display_name": "Load"}]})
    token = call(base, "POST", "/auth/login", {"email": "load@example.com",
                                               "password": "correct horse"})[2]["token"]
    auth = {"Authorization": f"Bearer {token}"}
    jobs = []
    for i in range(50):
        kind = i % 5
        if kind == 0:
            jobs.append(("POST", "/auth/signup", {"email": f"user{i}@example.com",
                                                  "password": "correct horse",
                                                  "display_name": f"U{i}"}, None))
        elif kind == 1:
            jobs.append(("POST", "/auth/login", {"email": "load@example.com",
                                                 "password": "correct horse"}, None))
        elif kind == 2:
            jobs.append(("GET", "/dossiers", None, auth))
        elif kind == 3:
            jobs.append(("GET", f"/dossiers/{domain}", None, auth))
        else:
            jobs.append(("POST", "/dossiers", {"domain": domain},
                         {**auth, "Idempotency-Key": f"load-{i}"}))
    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(lambda j: call(base, j[0], j[1], j[2], j[3]), jobs))
    worst = max(seconds for _, seconds, _ in results)
    errors = [status for status, _, _ in results if status >= 500]
    print(f"50 requests: 5xx={len(errors)} slowest={worst:.2f}s")
    while True:
        status, _, body = call(base, "GET", f"/dossiers/{domain}", headers=auth)
        if status == 200 and body["state"] != "building":
            break
        time.sleep(0.1)
    build_seconds = time.monotonic() - began
    print(f"build of {domain}: {body['state']} after {build_seconds:.2f}s, "
          f"{body['spent_units']} units")
    return 0 if not errors and worst < 5 and build_seconds < 10 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
