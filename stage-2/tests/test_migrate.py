"""Importing a stage-1 export into stage 2 (stage-2 "Existing clients after an upgrade").

The fixture is a real export of the frozen stage-1 service built against the harness mock
(synthetic users only); it also records the bearer token the export's user signed in with.
"""
import json
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeWeb

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "stage1-export.json").read_text())
EXPORT, TOKEN = FIXTURE["export"], FIXTURE["token"]


@pytest.fixture
def client():
    web = FakeWeb()
    with TestClient(create_app(web_factory=lambda: web)) as c:
        c.post("/_test/reset", json={"now": "2026-03-02T09:00:00+00:00", "users": []})
        assert c.post("/_test/import", json=EXPORT).status_code == 204
        c.web = web
        yield c


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_old_token_still_signs_in(client):
    assert client.get("/dossiers", headers=auth()).status_code == 200


def test_fields_get_one_candidate_per_cited_page(client):
    for exported in EXPORT["state"]["dossiers"]:
        body = client.get(f"/dossiers/{exported['domain']}", headers=auth()).json()
        assert body["dossier_id"] == exported["dossier_id"]
        assert body["state"] == exported["state"]
        assert body["spent_units"] == exported["spent_units"]
        for name, old in exported["fields"].items():
            field = body["fields"][name]
            assert field["value"] == old["value"]
            assert field["status"] == old["status"]          # stage-1 fields are never contested
            urls = list(dict.fromkeys(c["url"] for c in old["citations"]))
            assert sorted(c["url"] for c in field["candidates"]) == sorted(urls)
            for candidate in field["candidates"]:
                first = next(c for c in old["citations"] if c["url"] == candidate["url"])
                assert candidate["excerpt"] == first["excerpt"]
                assert candidate["provider"] == first["provider"]
                assert candidate["kind"] is None and candidate["published_at"] is None
                assert candidate["retrieved_at"] == exported["researched_at"]
            assert [c["selected"] for c in field["candidates"]][:1] in ([], [True])


def test_lost_responses_replay_after_import(client):
    for record in EXPORT["state"]["idempotency"]:
        headers = {**auth(), "Idempotency-Key": record["key"]}
        if record["path"] == "/dossiers":
            domain = next(d["domain"] for d in EXPORT["state"]["dossiers"]
                          if d["dossier_id"] == record["body"]["dossier_id"])
            r = client.post("/dossiers", json={"domain": domain}, headers=headers)
        else:
            r = client.post(record["path"], headers=headers)
        assert r.status_code == 200 and r.json() == record["body"]
    assert client.web.calls == []                             # no build was started


def test_next_build_replaces_imported_candidates(client):
    domain = "halvorsen-robotics.test"
    r = client.post(f"/dossiers/{domain}/refresh", headers={**auth(), "Idempotency-Key": "new"})
    assert r.status_code == 202
    for _ in range(200):
        body = client.get(f"/dossiers/{domain}", headers=auth()).json()
        if body["state"] != "building":
            break
        time.sleep(0.02)
    kinds = {c["kind"] for f in body["fields"].values() for c in f["candidates"]}
    assert None not in kinds


def test_stage2_export_round_trips_and_mixed_shapes_import(client):
    exported = client.get("/_test/export").json()
    assert exported["format_version"] == 1
    assert all("candidates" in f for d in exported["state"]["dossiers"]
               for f in d["fields"].values())
    assert client.post("/_test/import", json=exported).status_code == 204
    assert client.get("/_test/export").json() == exported
    mixed = json.loads(json.dumps(exported))
    mixed["state"]["dossiers"][0] = EXPORT["state"]["dossiers"][0]   # one stage-1 dossier
    assert client.post("/_test/import", json=mixed).status_code == 204


def test_invalid_stage1_state_changes_nothing(client):
    before = client.get("/_test/export").json()
    bad = json.loads(json.dumps(EXPORT))
    bad["state"]["dossiers"][0]["fields"]["ceo"]["status"] = "contested"   # not a stage-1 status
    assert client.post("/_test/import", json=bad).status_code == 422
    bad = json.loads(json.dumps(EXPORT))
    bad["state"]["dossiers"][0]["fields"]["ceo"]["candidates"] = [{"value": "x"}]
    assert client.post("/_test/import", json=bad).status_code == 422
    assert client.get("/_test/export").json() == before


@pytest.mark.parametrize("field, bad", [
    ("headcount_range", "banana"), ("headcount_range", "51-199"), ("founded_year", 1700),
    ("founded_year", 2014.0), ("funding_total", -5), ("ceo", "  "), ("legal_name", ""),
])
def test_stage2_values_outside_the_field_format_are_422(client, field, bad):
    exported = client.get("/_test/export").json()
    dossier = next(d for d in exported["state"]["dossiers"] if d["fields"][field]["candidates"])
    broken = json.loads(json.dumps(exported))
    target = next(d for d in broken["state"]["dossiers"] if d["dossier_id"] == dossier["dossier_id"])
    target["fields"][field]["value"] = bad
    for candidate in target["fields"][field]["candidates"]:
        candidate["value"] = bad
    assert client.post("/_test/import", json=broken).status_code == 422
    assert client.get("/_test/export").json() == exported


def test_stage2_field_inconsistent_with_its_candidates_is_422(client):
    exported = client.get("/_test/export").json()
    broken = json.loads(json.dumps(exported))
    field = next(f for d in broken["state"]["dossiers"] for f in d["fields"].values()
                 if f["candidates"])
    field["status"] = "contested"
    assert client.post("/_test/import", json=broken).status_code == 422


def test_stage1_values_outside_the_field_format_are_422(client):
    before = client.get("/_test/export").json()
    bad = json.loads(json.dumps(EXPORT))
    bad["state"]["dossiers"][0]["fields"]["headcount_range"]["value"] = "banana"
    assert client.post("/_test/import", json=bad).status_code == 422
    assert client.get("/_test/export").json() == before
