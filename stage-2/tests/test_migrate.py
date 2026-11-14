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


# ---------------------------------------------------------------- every JSON type, every slot

JSON_SAMPLES = [[], {}, None, True, False, 1.5, 7, -7, 0, "x", "", " x ", [[1]], {"a": [1]},
                ["51-200"], {"value": 2014}]
FIELD_NAMES = ["legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total"]


def _bad_values(field):
    """Every sample that is not a value §4 allows for ``field``."""
    from app.migrate import in_field_format
    return [v for v in JSON_SAMPLES if not in_field_format(field, v)]


def _stage2_export(client):
    exported = client.get("/_test/export").json()
    dossier = next(d for d in exported["state"]["dossiers"]
                   if all(d["fields"][f]["candidates"] for f in FIELD_NAMES))
    return exported, dossier["dossier_id"]


def _assert_rejected(client, payload, before):
    r = client.post("/_test/import", json=payload)
    assert r.status_code == 422, (r.status_code, r.text)
    assert r.json()["error"]["code"] == "validation_failed"
    assert client.get("/_test/export").json() == before


@pytest.mark.parametrize("field", FIELD_NAMES)
@pytest.mark.parametrize("slot", ["field", "candidate", "both", "stage1"])
def test_every_json_type_in_every_value_slot_is_422(client, field, slot):
    exported, dossier_id = _stage2_export(client)
    for bad in _bad_values(field):
        payload = json.loads(json.dumps(exported if slot != "stage1" else EXPORT))
        source = payload["state"]["dossiers"]
        target = next(d for d in source if d["dossier_id"] == dossier_id) if slot != "stage1" \
            else next(d for d in source if d["fields"][field]["value"] is not None)
        if slot in ("field", "both", "stage1"):
            target["fields"][field]["value"] = bad
        if slot in ("candidate", "both"):
            target["fields"][field]["candidates"][0]["value"] = bad
        _assert_rejected(client, payload, exported)


@pytest.mark.parametrize("key", ["url", "excerpt", "provider", "kind", "published_at",
                                 "retrieved_at", "selected"])
def test_every_json_type_in_other_candidate_slots_never_500(client, key):
    exported, dossier_id = _stage2_export(client)
    for sample in JSON_SAMPLES:
        payload = json.loads(json.dumps(exported))
        target = next(d for d in payload["state"]["dossiers"] if d["dossier_id"] == dossier_id)
        candidate = target["fields"]["ceo"]["candidates"][0]
        if candidate[key] == sample:
            continue
        candidate[key] = sample
        r = client.post("/_test/import", json=payload)
        assert r.status_code == 422, (key, sample, r.status_code)
        assert client.get("/_test/export").json() == exported


@pytest.mark.parametrize("slot", ["status", "citations", "candidates", "fields", "citation",
                                  "state", "researched_at", "spent_units", "domain"])
def test_every_json_type_in_field_and_dossier_slots_never_500(client, slot):
    exported, dossier_id = _stage2_export(client)
    for sample in JSON_SAMPLES:
        payload = json.loads(json.dumps(exported))
        target = next(d for d in payload["state"]["dossiers"] if d["dossier_id"] == dossier_id)
        field = target["fields"]["ceo"]
        if slot in ("status", "citations", "candidates"):
            field[slot] = sample
        elif slot == "citation":
            field["citations"][0] = sample
        elif slot == "fields":
            target["fields"] = sample
        else:
            target[slot] = sample
        r = client.post("/_test/import", json=payload)
        assert r.status_code in (204, 422), (slot, sample, r.status_code)
        if r.status_code == 422:
            assert client.get("/_test/export").json() == exported
        else:
            client.post("/_test/import", json=exported)


def test_researched_at_must_be_a_timestamp(client):
    before = client.get("/_test/export").json()
    for sample in ["yesterday", 5, [], {}, True]:
        bad = json.loads(json.dumps(EXPORT))
        bad["state"]["dossiers"][0]["researched_at"] = sample
        _assert_rejected(client, bad, before)


# ---------------------------------------------------------------- excerpts must support values

def _self_consistent(field, candidates):
    """The field the selection rule makes of ``candidates`` (so only support can fail)."""
    from app.selection import Candidate, decide_field
    return decide_field([Candidate.from_json(field, c) for c in candidates])


def _built_export():
    """A real stage-2 export: one build with agreeing and disagreeing pages."""
    from tests.fakes import DOMAIN, PAGES
    pages = dict(PAGES)
    pages["https://bizdata.test/acme"] = "Kind: aggregator\n\nAcme Robotics CEO: Sam Ortiz."
    web = FakeWeb(pages=pages)
    with TestClient(create_app(web_factory=lambda: web)) as c:
        c.post("/_test/reset", json={"now": "2026-03-01T09:00:00+00:00", "users": [
            {"id": "u_a", "email": "a@example.com", "password": "correct horse",
             "display_name": "A"}]})
        token = c.post("/auth/login", json={"email": "a@example.com",
                                            "password": "correct horse"}).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        c.post("/dossiers", json={"domain": DOMAIN}, headers={**h, "Idempotency-Key": "k"})
        for _ in range(200):
            if c.get(f"/dossiers/{DOMAIN}", headers=h).json()["state"] != "building":
                break
            time.sleep(0.02)
        return c.get("/_test/export").json()


def test_stage2_build_export_round_trips_unchanged(client):
    exported = _built_export()
    fields = exported["state"]["dossiers"][0]["fields"]
    assert fields["ceo"]["status"] == "contested"
    assert client.post("/_test/import", json=exported).status_code == 204
    assert client.get("/_test/export").json() == exported


def test_stage1_fixture_imports_cleanly(client):
    assert client.post("/_test/import", json=EXPORT).status_code == 204


def _tamper_stage2(exported, change):
    payload = json.loads(json.dumps(exported))
    dossier = payload["state"]["dossiers"][0]
    change(dossier)
    return payload


@pytest.mark.parametrize("case", ["changed_value", "wrong_field", "wrong_domain",
                                  "multi_sentence"])
def test_stage2_tampered_candidates_are_422(client, case):
    exported = _built_export()
    client.post("/_test/import", json=exported)

    def change(dossier):
        fields = dossier["fields"]
        if case == "changed_value":     # 2014 is cited by "... founded in 2014."
            cands = fields["founded_year"]["candidates"]
            cands[0]["value"] = 2015
            fields["founded_year"] = _self_consistent("founded_year", cands)
        elif case == "wrong_field":     # a CEO sentence offered as the headquarters
            moved = dict(fields["ceo"]["candidates"][0])
            fields["hq_city"] = _self_consistent("hq_city", [moved])
        elif case == "wrong_domain":    # the excerpts name acme-robotics, not this domain
            dossier["domain"] = "other-company.test"
        else:                           # two sentences
            cands = fields["founded_year"]["candidates"]
            cands[0]["excerpt"] += " It grew."
            fields["founded_year"] = _self_consistent("founded_year", cands)

    _assert_rejected(client, _tamper_stage2(exported, change), exported)


@pytest.mark.parametrize("case", ["changed_value", "wrong_field", "wrong_domain",
                                  "multi_sentence"])
def test_stage1_tampered_citations_are_422(client, case):
    before = client.get("/_test/export").json()
    payload = json.loads(json.dumps(EXPORT))
    dossier = next(d for d in payload["state"]["dossiers"]
                   if d["fields"]["founded_year"]["value"] is not None)
    fields = dossier["fields"]
    if case == "changed_value":
        fields["founded_year"]["value"] += 1
    elif case == "wrong_field":
        fields["hq_city"]["citations"] = fields["ceo"]["citations"]
        fields["hq_city"]["value"] = fields["ceo"]["value"]
    elif case == "wrong_domain":
        dossier["domain"] = "other-company.test"
    else:
        fields["founded_year"]["citations"][0]["excerpt"] += " It grew."
    _assert_rejected(client, payload, before)
