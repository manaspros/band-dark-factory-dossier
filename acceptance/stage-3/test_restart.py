"""Opt-in durability check against an explicitly named disposable container."""
from __future__ import annotations

import subprocess

import pytest

from conftest import (API, TEST_DOMAIN, create_build, feed, history, new_key,
                      parse_instant, refresh_build, wait_healthy)


def test_committed_state_survives_container_kill_and_start(api: API, token: str,
                                                            restart_container: str) -> None:
    """T67-T74: saved identities, dossier views, feed, idempotency and clock survive restart."""
    key = new_key()
    ready, initial = create_build(api, token, key=key)
    # Try for a feed entry; if the fixed corpus is unchanged, durability is still checked
    # against the existing history and feed snapshot.
    refreshed, _ = refresh_build(api, token)
    before_feed = feed(api, token)
    before = {
        "dossier": api.get(f"/dossiers/{TEST_DOMAIN}", token=token).json(),
        "as_of": api.get(f"/dossiers/{TEST_DOMAIN}?as_of={ready['researched_at']}",
                         token=token).json(),
        "values": api.get(f"/dossiers/{TEST_DOMAIN}/values?true_at=2099-12-31",
                          token=token).json(),
        "history": history(api, token, TEST_DOMAIN),
        "list": api.get("/dossiers", token=token).json(),
    }
    assert parse_instant(refreshed["researched_at"]) >= parse_instant(ready["researched_at"])
    subprocess.run(["docker", "kill", restart_container], check=True, capture_output=True,
                   text=True, timeout=30)
    subprocess.run(["docker", "start", restart_container], check=True, capture_output=True,
                   text=True, timeout=30)
    wait_healthy(api, timeout=90)

    # Existing token and password both remain usable.
    assert api.get(f"/dossiers/{TEST_DOMAIN}", token=token).status_code == 200
    assert api.login()
    after = {
        "dossier": api.get(f"/dossiers/{TEST_DOMAIN}", token=token).json(),
        "as_of": api.get(f"/dossiers/{TEST_DOMAIN}?as_of={ready['researched_at']}",
                         token=token).json(),
        "values": api.get(f"/dossiers/{TEST_DOMAIN}/values?true_at=2099-12-31",
                          token=token).json(),
        "history": history(api, token, TEST_DOMAIN),
        "list": api.get("/dossiers", token=token).json(),
    }
    assert after == before
    assert feed(api, token) == before_feed
    replay = api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                      json={"domain": TEST_DOMAIN})
    assert replay.status_code == 200, replay.text
    assert replay.json() == initial.json()
