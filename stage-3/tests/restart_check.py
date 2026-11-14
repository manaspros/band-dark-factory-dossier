"""Restart check against a running container (run by hand, not by pytest; stage-3 "Restarts").

    python tests/restart_check.py http://localhost:8080 <container> <domain> <domain>

1. Reset, sign up, build both dossiers, refresh the first at a later clock time, then move
   the clock again. Record every endpoint's answer (with and without `as_of`, `/values`,
   `/history`, `/dossiers`, `/changes`) and the export.
2. `docker kill` (SIGKILL) the container, `docker start` it, wait for `/health`.
3. Every answer and the export must be identical; the password signs in; the old token is
   valid; a completed idempotent refresh replays; the clock still reads the time it read.
4. Fire 50 concurrent writes (signups and dossier creations) and SIGKILL the container while
   they run. After a restart, every acknowledged write must be there (its account signs in,
   its token is valid, its creation replays with the same answer) and every dossier listed
   must answer.

Needs only the standard library and the `docker` command.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

T1, T2, T3 = ("2026-03-01T09:00:00+00:00", "2026-04-01T09:00:00+00:00",
              "2026-05-01T09:00:00+00:00")
PASSWORD = "correct horse"


def call(base, method, path, body=None, headers=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"content-type": "application/json",
                                              **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    return status, json.loads(raw) if raw else None


def wait_health(base, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if call(base, "GET", "/health", timeout=2)[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.25)
    raise SystemExit("service did not come back")


def restart(container, base):
    subprocess.run(["docker", "kill", container], check=True, capture_output=True)
    subprocess.run(["docker", "start", container], check=True, capture_output=True)
    wait_health(base)


def wait_built(base, auth, domain):
    for _ in range(300):
        status, body = call(base, "GET", f"/dossiers/{domain}", headers=auth)
        if status == 200 and body["state"] != "building":
            return body
        time.sleep(0.2)
    raise SystemExit(f"{domain} never finished building")


def check(label, condition, failures):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        failures.append(label)


def endpoints(domains):
    paths = ["/dossiers", "/changes", "/changes?since=0&limit=200"]
    for d in domains:
        paths += [f"/dossiers/{d}", f"/dossiers/{d}?as_of={T1}", f"/dossiers/{d}?as_of={T3}",
                  f"/dossiers/{d}?as_of=2000-01-01T00:00:00Z",
                  f"/dossiers/{d}/values?true_at=2025-06-01",
                  f"/dossiers/{d}/values?true_at=2025-06-01&as_of={T1}",
                  f"/dossiers/{d}/history"]
    return paths


def snapshot(base, auth, domains):
    answers = {p: call(base, "GET", p, headers=auth) for p in endpoints(domains)}
    answers["export"] = call(base, "GET", "/_test/export")
    return answers


def phase_one(base, container, domains, failures):
    call(base, "POST", "/_test/reset", {"now": T1, "users": []})
    status, user = call(base, "POST", "/auth/signup", {"email": "restart@example.com",
                                                       "password": PASSWORD,
                                                       "display_name": "Restart"})
    assert status == 201, user
    auth = {"Authorization": f"Bearer {user['token']}"}
    for i, domain in enumerate(domains):
        call(base, "POST", "/dossiers", {"domain": domain},
             {**auth, "Idempotency-Key": f"create-{i}"})
        wait_built(base, auth, domain)
    call(base, "POST", "/_test/clock", {"now": T2})
    refresh = call(base, "POST", f"/dossiers/{domains[0]}/refresh", None,
                   {**auth, "Idempotency-Key": "refresh-1"})
    wait_built(base, auth, domains[0])
    call(base, "POST", "/_test/clock", {"now": T3})
    before = snapshot(base, auth, domains)
    seqs = [c["seq"] for c in before["/changes?since=0&limit=200"][1]["changes"]]
    print(f"recorded {len(before)} answers; feed entries before the stop: {len(seqs)}")

    restart(container, base)
    after = snapshot(base, auth, domains)
    for path in before:
        check(f"same answer after restart: {path}", before[path] == after[path], failures)
    status, login = call(base, "POST", "/auth/login", {"email": "restart@example.com",
                                                       "password": PASSWORD})
    check("password signs in after restart", status == 200, failures)
    check("old token valid after restart",
          call(base, "GET", "/dossiers", headers=auth)[0] == 200, failures)
    check("completed refresh replays after restart",
          call(base, "POST", f"/dossiers/{domains[0]}/refresh", None,
               {**auth, "Idempotency-Key": "refresh-1"}) == (200, refresh[1]), failures)
    values = call(base, "GET", f"/dossiers/{domains[0]}/values?true_at=2025-06-01",
                  headers=auth)[1]
    check("clock reads the time it read before the stop", values["as_of"] == T3, failures)
    check("clock cannot be moved back after restart",
          call(base, "POST", "/_test/clock", {"now": T2})[0] == 422, failures)
    call(base, "POST", "/_test/clock", {"now": "2026-06-01T09:00:00+00:00"})
    call(base, "POST", f"/dossiers/{domains[1]}/refresh", None,
         {**auth, "Idempotency-Key": "refresh-2"})
    wait_built(base, auth, domains[1])
    later = [c["seq"] for c in call(base, "GET", "/changes?limit=200", headers=auth)[1]["changes"]]
    new = later[len(seqs):]
    check(f"feed keeps its entries; new entries ({len(new)}) have larger seq",
          later[:len(seqs)] == seqs and all(s > max(seqs, default=0) for s in new), failures)
    return auth


def phase_two(base, container, domains, auth, failures):
    acknowledged: list[tuple[str, dict, object]] = []
    lock = threading.Lock()

    def write(i):
        try:
            if i % 2:
                body = {"email": f"load{i}@example.com", "password": PASSWORD,
                        "display_name": f"Load {i}"}
                status, answer = call(base, "POST", "/auth/signup", body, timeout=15)
                kind = ("signup", body, answer)
            else:
                key = f"burst-{i}"
                status, answer = call(base, "POST", "/dossiers", {"domain": f"burst{i}.test"},
                                      {**auth, "Idempotency-Key": key}, timeout=15)
                kind = ("create", {"domain": f"burst{i}.test", "key": key}, answer)
        except OSError:
            return
        if 200 <= status < 300:
            with lock:
                acknowledged.append(kind)

    with ThreadPoolExecutor(max_workers=50) as pool:
        futures = [pool.submit(write, i) for i in range(50)]
        deadline = time.monotonic() + 5   # stop the container once a few have answered
        while len(acknowledged) < 5 and time.monotonic() < deadline:
            time.sleep(0.005)
        subprocess.run(["docker", "kill", container], check=True, capture_output=True)
        for f in futures:
            f.result()
    print(f"acknowledged before the kill: {len(acknowledged)} of 50")
    check("the kill landed mid-burst", len(acknowledged) < 50, failures)
    subprocess.run(["docker", "start", container], check=True, capture_output=True)
    wait_health(base)
    for kind, body, answer in acknowledged:
        if kind == "signup":
            ok = (call(base, "POST", "/auth/login", {"email": body["email"],
                                                     "password": PASSWORD})[0] == 200
                  and call(base, "GET", "/dossiers",
                           headers={"Authorization": f"Bearer {answer['token']}"})[0] == 200)
        else:
            ok = call(base, "POST", "/dossiers", {"domain": body["domain"]},
                      {**auth, "Idempotency-Key": body["key"]}) == (200, answer)
        check(f"acknowledged {kind} survived: {body.get('email') or body['domain']}", ok,
              failures)
    listed = call(base, "GET", "/dossiers?limit=200", headers=auth)[1]["dossiers"]
    check("every listed dossier answers",
          all(call(base, "GET", f"/dossiers/{d['domain']}", headers=auth)[0] == 200
              for d in listed), failures)


def main(base, container, *domains):
    failures: list[str] = []
    auth = phase_one(base, container, list(domains), failures)
    phase_two(base, container, list(domains), auth, failures)
    print(f"restart check: {'FAILED ' + str(len(failures)) if failures else 'passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
