"""Stage 1 compatibility, clock and HTML/API authorization boundaries."""
from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import API, FIELDS, TEST_DOMAIN, begin_dossier, new_key, wait_dossier


def _to_stage1_state(value):
    """Turn exported Stage 2 field records into the documented Stage 1 shape."""
    if isinstance(value, list):
        return [_to_stage1_state(item) for item in value]
    if not isinstance(value, dict):
        return value
    converted = {key: _to_stage1_state(item) for key, item in value.items()
                 if key != "candidates"}
    if {"value", "status", "citations"} <= converted.keys():
        converted["status"] = "unknown" if converted["value"] is None else "known"
    return converted


def test_stage1_shaped_import_keeps_session_dossier_and_replay(api: API, token: str) -> None:
    """S108-S116 / Stage 1 R199-R213: import preserves identities and makes citation candidates."""
    key = new_key()
    original = begin_dossier(api, token, TEST_DOMAIN, key)
    assert original.status_code == 202, original.text
    original_body = original.json()
    ready = wait_dossier(api, token, TEST_DOMAIN)
    assert ready["state"] == "ready", ready

    exported = api.get("/_test/export")
    assert exported.status_code == 200, exported.text
    stage1_export = deepcopy(exported.json())
    assert stage1_export["track"] == "dossier" and stage1_export["format_version"] == 1
    stage1_export["state"] = _to_stage1_state(stage1_export["state"])

    # Import replaces all state. The existing token and successful idempotency response
    # must remain usable, while candidates are reconstructed from exported citations.
    imported = api.post("/_test/import", json=stage1_export, timeout=10)
    assert imported.status_code == 204, imported.text
    replay = api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                      json={"domain": TEST_DOMAIN})
    assert replay.status_code == 200, replay.text
    assert replay.json() == original_body

    dossier = api.get(f"/dossiers/{TEST_DOMAIN}", token=token)
    assert dossier.status_code == 200, dossier.text
    restored = dossier.json()
    assert restored["dossier_id"] == ready["dossier_id"]
    assert restored["researched_at"] == ready["researched_at"]
    assert restored["spent_units"] == ready["spent_units"]
    assert list(restored["fields"]) == list(FIELDS)
    for name in FIELDS:
        field = restored["fields"][name]
        assert field["status"] in ("known", "unknown")
        if field["value"] is None:
            assert field["candidates"] == []
        else:
            assert field["candidates"], field
        for candidate in field["candidates"]:
            assert candidate["kind"] is None
            assert candidate["published_at"] is None
            assert candidate["retrieved_at"] == restored["researched_at"]
        if field["value"] is None:
            assert field["status"] == "unknown" and field["citations"] == []
        else:
            assert field["status"] == "known"
            assert all(c["value"] == field["value"] for c in field["candidates"])


def test_clock_moves_forward_and_rejects_backwards_time(api: API, token: str) -> None:
    """Stage 1 R27-R30: the test clock is stable, monotonic and drives build timestamps."""
    moved = api.post("/_test/clock", json={"now": "2026-03-01T09:15:00+00:00"})
    assert moved.status_code == 204, moved.text
    first = begin_dossier(api, token, "clock-check.test")
    assert first.status_code == 202, first.text
    ready = wait_dossier(api, token, "clock-check.test")
    assert ready["researched_at"] == "2026-03-01T09:15:00+00:00"
    rejected = api.post("/_test/clock", json={"now": "2026-03-01T09:14:59+00:00"})
    assert rejected.status_code == 422, rejected.text
    same = api.get("/dossiers/clock-check.test", token=token)
    assert same.json()["researched_at"] == ready["researched_at"]


@pytest.mark.parametrize("path", ["/", "/signup", "/login", "/contested",
                                   "/dossiers/shell-one.test",
                                   "/dossiers/shell-one.test/evidence"])
def test_html_routes_are_public_data_free_shells(api: API, path: str) -> None:
    """S46/E19: six routes return the same no-data shell; JSON dossier reads require auth."""
    response = api.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers.get("Content-Type", "")
    assert "shell-one.test" not in response.text
    # Route-specific path data must not be embedded in this public static shell.
    other = path.replace("shell-one.test", "shell-two.test")
    second = api.get(other, headers={"Accept": "text/html"})
    assert second.status_code == 200
    assert "shell-two.test" not in second.text


def test_shared_dossier_json_route_stays_authenticated(api: API) -> None:
    """Stage 1 R99 + E19: HTML shell is public; the same route's JSON remains protected."""
    response = api.get("/dossiers/private-shell.test", headers={"Accept": "application/json"})
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "unauthenticated"
