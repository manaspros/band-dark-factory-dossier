"""Stage 1/2 upgrades and Stage 3 export round trips (T45, T55-T65)."""
from __future__ import annotations

from copy import deepcopy
from urllib.parse import quote

from conftest import (API, FIELDS, FIELDS7, TEST_DOMAIN, create_build, feed, history,
                      new_key, parse_instant, refresh_build, set_clock,
                      stage1_shaped_export, stage2_shaped_export)


def _as_of(api: API, token: str, domain: str, timestamp: str):
    return api.get(f"/dossiers/{domain}?as_of={quote(timestamp, safe='')}", token=token)


def test_stage1_shaped_import_rebuilds_candidates_and_keeps_token_replay(api: API,
                                                                          token: str) -> None:
    key = new_key()
    ready, first_response = create_build(api, token, key=key)
    original_response = first_response.json()
    raw_export = api.get("/_test/export")
    assert raw_export.status_code == 200, raw_export.text
    stage1_export = stage1_shaped_export(deepcopy(raw_export.json()))

    imported = api.post("/_test/import", json=stage1_export, timeout=10)
    assert imported.status_code == 204, imported.text
    replay = api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                      json={"domain": TEST_DOMAIN})
    assert replay.status_code == 200, replay.text
    assert replay.json() == original_response

    restored_response = api.get(f"/dossiers/{TEST_DOMAIN}", token=token)
    assert restored_response.status_code == 200, restored_response.text
    restored = restored_response.json()
    assert restored["dossier_id"] == ready["dossier_id"]
    assert restored["researched_at"] == ready["researched_at"]
    assert restored["spent_units"] == ready["spent_units"]
    assert list(restored["fields"]) == list(FIELDS7)
    for name in FIELDS:
        field = restored["fields"][name]
        assert field["candidates"] == sorted(field["candidates"],
                                               key=__import__("conftest").stage2_rank_key)
        if field["value"] is None:
            assert field["status"] == "unknown" and field["citations"] == []
            assert field["candidates"] == []
        else:
            assert field["candidates"]
            assert field["status"] in ("known", "contested")
            assert all(candidate["kind"] is None and candidate["published_at"] is None
                       and candidate["true_from"] is None for candidate in field["candidates"])
            assert all(candidate["learned_at"] == candidate["retrieved_at"]
                       for candidate in field["candidates"])
    assert restored["fields"]["executives"]["value"] is None
    assert restored["fields"]["executives"]["status"] == "unknown"

    history_response = history(api, token, TEST_DOMAIN)
    assert history_response["fields"]["executives"] == []
    assert feed(api, token)["changes"] == []
    before = _as_of(api, token, TEST_DOMAIN, "2026-03-01T08:59:59+00:00")
    after = _as_of(api, token, TEST_DOMAIN, "2026-03-01T09:00:00+00:00")
    assert before.status_code == 404, before.text
    assert after.status_code == 200, after.text
    assert after.json()["fields"] == restored["fields"]
    values = api.get(f"/dossiers/{TEST_DOMAIN}/values?true_at=2099-12-31", token=token)
    assert values.status_code == 200, values.text
    assert all(field["value"] is None and field["true_from"] is None
               and field["citations"] == [] for field in values.json()["fields"].values())


def test_stage2_shaped_import_preserves_candidates_spend_and_migrates_times(api: API,
                                                                            token: str) -> None:
    ready, _ = create_build(api, token)
    envelope = api.get("/_test/export")
    assert envelope.status_code == 200, envelope.text
    exported = stage2_shaped_export(deepcopy(envelope.json()))
    imported = api.post("/_test/import", json=exported, timeout=10)
    assert imported.status_code == 204, imported.text

    response = api.get(f"/dossiers/{TEST_DOMAIN}", token=token)
    assert response.status_code == 200, response.text
    dossier = response.json()
    assert dossier["dossier_id"] == ready["dossier_id"]
    assert dossier["spent_units"] == ready["spent_units"]
    assert dossier["researched_at"] == ready["researched_at"]
    assert list(dossier["fields"]) == list(FIELDS7)
    assert feed(api, token)["changes"] == []
    assert history(api, token, TEST_DOMAIN)["fields"]["executives"] == []
    assert dossier["fields"]["executives"]["value"] is None
    assert dossier["fields"]["executives"]["status"] == "unknown"

    for name in FIELDS:
        field = dossier["fields"][name]
        for candidate in field["candidates"]:
            expected = None
            if candidate["published_at"]:
                from datetime import timezone
                expected = parse_instant(candidate["published_at"]).astimezone(
                    timezone.utc).date().isoformat()
            assert candidate["true_from"] == expected
            assert candidate["learned_at"] == candidate["retrieved_at"]
        if field["value"] is None:
            assert history(api, token, TEST_DOMAIN)["fields"][name] == []
        else:
            entries = history(api, token, TEST_DOMAIN)["fields"][name]
            assert len(entries) == 1 and entries[0]["type"] == "initial"
            assert entries[0]["learned_at"] == dossier["researched_at"]
            assert entries[0]["true_from"] == field["true_from"]

    before = _as_of(api, token, TEST_DOMAIN, "2026-03-01T08:59:59+00:00")
    at = _as_of(api, token, TEST_DOMAIN, dossier["researched_at"])
    assert before.status_code == 404, before.text
    assert at.status_code == 200, at.text
    assert at.json()["spent_units"] == ready["spent_units"]


def test_stage3_export_import_round_trip_keeps_builds_history_and_feed(api: API,
                                                                      token: str,
                                                                      mock_admin) -> None:
    key = new_key()
    first, _ = create_build(api, token, key=key)
    set_clock(api, "2026-03-01T09:01:00+00:00")
    second, _ = refresh_build(api, token)

    def snapshot() -> dict:
        results = {
            "dossier": api.get(f"/dossiers/{TEST_DOMAIN}", token=token).json(),
            "history": history(api, token, TEST_DOMAIN),
            "feed": feed(api, token),
            "list": api.get("/dossiers", token=token).json(),
            "values": api.get(f"/dossiers/{TEST_DOMAIN}/values?true_at=2099-12-31",
                               token=token).json(),
            "as_of_first": _as_of(api, token, TEST_DOMAIN, first["researched_at"]).json(),
            "as_of_second": _as_of(api, token, TEST_DOMAIN, second["researched_at"]).json(),
        }
        return results

    before = snapshot()
    export_response = api.get("/_test/export")
    assert export_response.status_code == 200, export_response.text
    export = export_response.json()
    calls_before = len(mock_admin.calls()) if mock_admin.enabled else None
    imported = api.post("/_test/import", json=export, timeout=10)
    assert imported.status_code == 204, imported.text
    assert snapshot() == before
    replay = api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                      json={"domain": TEST_DOMAIN})
    assert replay.status_code == 200, replay.text
    assert replay.json() == {"dossier_id": first["dossier_id"], "domain": TEST_DOMAIN,
                             "state": "building"}
    if mock_admin.enabled:
        assert len(mock_admin.calls()) == calls_before, "import/replay made a provider call"


def test_invalid_import_is_rejected_without_replacing_existing_state(api: API, token: str) -> None:
    """Stage 1 §10: invalid import stays a validation response and preserves destination data."""
    ready, _ = create_build(api, token)
    before = api.get(f"/dossiers/{TEST_DOMAIN}", token=token).json()
    malformed = api.get("/_test/export").json()
    malformed["track"] = "other"
    response = api.post("/_test/import", json=malformed, timeout=10)
    assert response.status_code == 422, response.text
    after = api.get(f"/dossiers/{TEST_DOMAIN}", token=token).json()
    assert after == before
    assert after["dossier_id"] == ready["dossier_id"]


def test_null_researched_at_stage1_and_stage2_imports_keep_spend_and_wait_for_ready(
        api: API, token: str) -> None:
    ready, _ = create_build(api, token)
    source = api.get("/_test/export").json()
    for converter in (stage1_shaped_export, stage2_shaped_export):
        null_time = deepcopy(source)
        null_time = converter(null_time)
        state = null_time["state"]
        # The export state is implementation-defined, so select the documented dossier record
        # through the known domain-bearing nested record, without inventing a fixture schema.
        dossier_record = _find_dossier_record(state, TEST_DOMAIN)
        dossier_record["researched_at"] = None
        dossier_record["state"] = "failed"
        if "spent_units" in dossier_record:
            dossier_record["spent_units"] = 7
        fields = dossier_record.get("fields", {})
        for name in FIELDS:
            field = fields.get(name)
            if isinstance(field, dict):
                field["value"] = None
                field["status"] = "unknown"
                field["citations"] = []
                if "candidates" in field:
                    field["candidates"] = []
        response = api.post("/_test/import", json=null_time, timeout=10)
        assert response.status_code == 204, response.text
        current = api.get(f"/dossiers/{TEST_DOMAIN}", token=token)
        assert current.status_code == 200, current.text
        assert current.json()["spent_units"] == 7
        for timestamp in ("1900-01-01T00:00:00+00:00", "2099-12-31T23:59:59+00:00"):
            assert _as_of(api, token, TEST_DOMAIN, timestamp).status_code == 404
        assert api.get(f"/dossiers/{TEST_DOMAIN}/values?true_at=2026-01-01", token=token).status_code == 404
        rebuilt, _ = refresh_build(api, token)
        after = _as_of(api, token, TEST_DOMAIN, rebuilt["researched_at"])
        assert after.status_code == 200, after.text
        assert after.json()["spent_units"] == rebuilt["spent_units"]
        values = api.get(f"/dossiers/{TEST_DOMAIN}/values?true_at=2026-01-01",
                         token=token)
        assert values.status_code == 200, values.text


def _find_dossier_record(value, domain: str) -> dict:
    if isinstance(value, dict):
        if value.get("domain") == domain and "researched_at" in value:
            return value
        for child in value.values():
            try:
                return _find_dossier_record(child, domain)
            except LookupError:
                pass
    elif isinstance(value, list):
        for child in value:
            try:
                return _find_dossier_record(child, domain)
            except LookupError:
                pass
    raise LookupError(domain)
