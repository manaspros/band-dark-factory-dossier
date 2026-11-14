"""Opt-in abrupt restart check, restricted to the explicitly named container (F75-F80)."""
from __future__ import annotations

import subprocess
import time

import pytest

from conftest import (API, DOMAIN, MockAdmin, create, feed, history, key, wait_batch,
                      wait_dossier, wait_healthy)


def test_committed_state_survives_kill_and_running_build_is_terminal(
        api: API, token: str, restart_container: str, mock_admin: MockAdmin) -> None:
    """F75-F80: saved state survives; an in-flight build is not left building after restart."""
    if not mock_admin.enabled:
        pytest.skip("controlled in-flight restart needs DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    ready, _ = create(api, token, DOMAIN)
    snapshot = {
        "dossier": api.get(f"/dossiers/{DOMAIN}", token=token).json(),
        "history": history(api, token),
        "feed": feed(api, token),
        "list": api.get("/dossiers", token=token).json(),
    }
    persisted_clock = "2026-03-02T10:15:00+00:00"
    clock_set = api.post("/_test/clock", json={"now": persisted_clock})
    assert clock_set.status_code == 204, clock_set.text
    # Delay provider responses so batch builds are in flight when the container is killed.
    mock_admin.reset()
    mock_admin.delay("nimble", ["search"], 5)
    batch_key = key()
    batch_body = {"domains": ["restart-a.test", "restart-b.test"], "budget_units": 100}
    pending = api.post("/batches", token=token,
                       headers={"Idempotency-Key": batch_key}, json=batch_body)
    assert pending.status_code == 202, pending.text
    assert [item["state"] for item in pending.json()["dossiers"]] == ["building", "building"]
    batch_id = pending.json()["batch_id"]
    end = time.monotonic() + 10
    while time.monotonic() < end:
        if any(call.get("method") == "search" for call in mock_admin.calls()):
            break
        time.sleep(0.05)
    assert any(call.get("method") == "search" for call in mock_admin.calls()), "no delayed provider call observed"
    in_flight = api.get(f"/batches/{batch_id}", token=token)
    assert in_flight.status_code == 200, in_flight.text
    assert in_flight.json()["state"] == "running", in_flight.json()
    subprocess.run(["docker", "kill", restart_container], check=True,
                   capture_output=True, text=True, timeout=30)
    subprocess.run(["docker", "start", restart_container], check=True,
                   capture_output=True, text=True, timeout=30)
    healthy_at = time.monotonic()
    wait_healthy(api)
    after = api.get(f"/dossiers/{DOMAIN}", token=token).json()
    assert time.monotonic() - healthy_at < 10
    assert after["state"] == "ready"
    assert after["fields"] == snapshot["dossier"]["fields"]
    assert history(api, token) == snapshot["history"]
    assert feed(api, token) == snapshot["feed"]
    batch = wait_batch(api, token, batch_id, timeout=10)
    assert batch["state"] == "done" and batch["spent_units"] <= batch["budget_units"]
    replay = api.post("/batches", token=token,
                      headers={"Idempotency-Key": batch_key}, json=batch_body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == pending.json()
    for entry in batch["dossiers"]:
        state = api.get(f"/dossiers/{entry['domain']}", token=token).json()
        assert state["state"] in ("ready", "failed")
    mock_admin.reset()
    clock_refresh = api.post(f"/dossiers/{DOMAIN}/refresh", token=token,
                             headers={"Idempotency-Key": key()})
    assert clock_refresh.status_code == 202, clock_refresh.text
    clock_result = wait_dossier(api, token, DOMAIN)
    assert clock_result["researched_at"] == persisted_clock
    resumed = api.post("/dossiers/restart-a.test/refresh", token=token,
                       headers={"Idempotency-Key": key()})
    assert resumed.status_code == 202, resumed.text
    assert wait_dossier(api, token, "restart-a.test")["state"] in ("ready", "failed")
    assert api.get(f"/dossiers/{DOMAIN}", token=token).status_code == 200
    assert api.login()
    assert ready["dossier_id"] == after["dossier_id"]
    assert api.get("/dossiers", token=token).status_code == 200
