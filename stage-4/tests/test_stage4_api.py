"""Stage-4 behaviour end to end through the TestClient with a fake provider: batches,
provider failure, origins in builds, investors, restarts during builds and upgrades
(F2, F16-F17, F55-F85, F97)."""
import json
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.db import Database
from app.main import Services, create_app
from app.store import Store
from tests.fakes import DOMAIN, FakeWeb

FIXTURES = Path(__file__).parent / "fixtures"
STAGE3 = json.loads((FIXTURES / "stage3-export.json").read_text())
T1, T2 = "2026-03-01T09:00:00+00:00", "2026-04-01T09:00:00+00:00"
USERS = [{"id": f"u_{n}", "email": f"{n}@example.com", "password": "correct horse",
          "display_name": n} for n in ("ada", "bob")]
OWN = f"https://{DOMAIN}/about"


def open_app(path, web):
    services = Services(store=Store(Database(str(path))))
    return TestClient(create_app(services, web_factory=lambda: web))


@pytest.fixture
def web():
    return FakeWeb(pages={OWN: "Kind: own\n\nAcme Robotics was founded in 2014. "
                               "Acme Robotics is backed by Northwind Ventures."})


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "dossier.db"


@pytest.fixture
def client(web, db_path):
    with open_app(db_path, web) as c:
        assert c.post("/_test/reset", json={"now": T1, "users": USERS}).status_code == 204
        yield c


def login(client, name="ada"):
    r = client.post("/auth/login", json={"email": f"{name}@example.com",
                                         "password": "correct horse"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def wait(client, h, path):
    for _ in range(400):
        body = client.get(path, headers=h).json()
        if body.get("state") not in ("building", "running"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"{path} still running")


def batch(client, h, body, key="b1"):
    return client.post("/batches", json=body, headers={**h, "Idempotency-Key": key})


def build(client, h, domain=DOMAIN, key="k1"):
    r = client.post("/dossiers", json={"domain": domain}, headers={**h, "Idempotency-Key": key})
    assert r.status_code in (200, 202), r.text
    return wait(client, h, f"/dossiers/{domain}")


# --------------------------------------------------------------------------- batches

@pytest.mark.parametrize("body, status", [
    ({"budget_units": 10}, 422),
    ({"domains": "a.test", "budget_units": 10}, 400),
    ({"domains": [], "budget_units": 10}, 422),
    ({"domains": [f"d{i}.test" for i in range(51)], "budget_units": 10}, 422),
    ({"domains": [1], "budget_units": 10}, 400),
    ({"domains": ["not a domain"], "budget_units": 10}, 422),
    ({"domains": ["Acme.test", "acme.test"], "budget_units": 10}, 422),
    ({"domains": ["a.test"]}, 422),
    ({"domains": ["a.test"], "budget_units": "200"}, 422),
    ({"domains": ["a.test"], "budget_units": True}, 422),
    ({"domains": ["a.test"], "budget_units": 1.5}, 422),
    ({"domains": ["a.test"], "budget_units": 100.0}, 422),
    ({"domains": ["a.test"], "budget_units": None}, 422),
    ({"domains": ["a.test"], "budget_units": [1]}, 422),
    ({"domains": ["a.test"], "budget_units": 0}, 422),
    ({"domains": ["a.test"], "budget_units": 100001}, 422),
])
def test_batch_validation(client, web, body, status):
    r = batch(client, login(client), body)
    assert r.status_code == status, r.text
    assert web.calls == [] and client.get("/dossiers", headers=login(client)).json()[
        "dossiers"] == []


def test_batch_runs_new_domains_under_its_budget(client, web):
    h = login(client)
    existing = build(client, h)
    calls_before = len(web.calls)
    r = batch(client, h, {"domains": ["new-one.test", DOMAIN.upper(), "new-two.test"],
                          "budget_units": 100})
    assert r.status_code == 202
    body = r.json()
    assert set(body) == {"batch_id", "state", "budget_units", "spent_units", "dossiers"}
    assert body["batch_id"].startswith("b_") and body["state"] == "running"
    assert body["budget_units"] == 100 and body["spent_units"] == 0
    assert body["dossiers"] == [{"domain": "new-one.test", "state": "building"},
                                {"domain": DOMAIN, "state": "ready"},
                                {"domain": "new-two.test", "state": "building"}]
    done = wait(client, h, f"/batches/{body['batch_id']}")
    assert done["state"] == "done" and 0 < done["spent_units"] <= 100
    spends = [client.get(f"/dossiers/{d}", headers=h).json()["spent_units"]
              for d in ("new-one.test", "new-two.test")]
    assert sum(spends) == done["spent_units"] and max(spends) <= 50    # each build's share
    assert client.get(f"/dossiers/{DOMAIN}", headers=h).json()["spent_units"] \
        == existing["spent_units"]                                    # not researched again
    assert not any(DOMAIN == a for _, a in web.calls[calls_before:])
    replay = batch(client, h, {"domains": ["new-one.test", DOMAIN.upper(), "new-two.test"],
                               "budget_units": 100})
    assert replay.status_code == 200 and replay.json() == body
    assert batch(client, h, {"domains": ["x.test"], "budget_units": 100}).status_code == 409


def test_batch_owner_auth_and_unknown(client):
    h = login(client)
    batch_id = batch(client, h, {"domains": ["a.test"], "budget_units": 50}).json()["batch_id"]
    assert client.get(f"/batches/{batch_id}", headers=login(client, "bob")).status_code == 404
    assert client.get("/batches/b_nope", headers=h).status_code == 404
    assert client.get(f"/batches/{batch_id}").status_code == 401
    assert client.post("/batches", json={}).status_code == 401
    assert client.post("/batches", json={"domains": ["a.test"], "budget_units": 5},
                       headers=h).json()["error"]["code"] == "missing_idempotency_key"


def test_tiny_budget_stops_the_batch_and_its_builds_end_ready(client, web):
    h = login(client)
    body = batch(client, h, {"domains": ["one.test", "two.test"], "budget_units": 1}).json()
    done = wait(client, h, f"/batches/{body['batch_id']}")
    assert done["state"] == "done" and done["spent_units"] <= 1
    states = [wait(client, h, f"/dossiers/{d}") for d in ("one.test", "two.test")]
    assert all(s["state"] == "ready" for s in states)
    assert all(f["status"] == "unknown" for s in states for f in s["fields"].values())
    assert sum(1 for m, _ in web.calls if m != "poll") <= 1


# --------------------------------------------------------------------------- provider failure

@pytest.mark.parametrize("failure", ["start_refused", "polls_fail", "never_done"])
def test_research_failure_still_ready_within_ten_seconds(db_path, failure):
    web = FakeWeb(pages={OWN: "Kind: own\n\nAcme Robotics was founded in 2014."},
                  refuse=(lambda m, a, n: 503 if m == "research" else False)
                  if failure == "start_refused" else None,
                  poll_failures=100 if failure == "polls_fail" else 0,
                  never_done=failure == "never_done")
    with open_app(db_path, web) as c:
        c.post("/_test/reset", json={"now": T1, "users": USERS})
        h = login(c)
        began = time.monotonic()
        body = build(c, h)
        assert time.monotonic() - began < 10
        assert body["state"] == "ready"
        if failure != "never_done":   # a run still going at the 8 s guard leaves no time to read
            assert body["fields"]["founded_year"]["value"] == 2014


def test_every_call_refused_fails_fast_and_costs_nothing(db_path):
    web = FakeWeb(refuse=lambda m, a, n: 503)
    with open_app(db_path, web) as c:
        c.post("/_test/reset", json={"now": T1, "users": USERS})
        h = login(c)
        began = time.monotonic()
        body = build(c, h)
        assert time.monotonic() - began < 10
        assert body["state"] == "failed" and body["spent_units"] == 0


# --------------------------------------------------------------------------- origins

def test_origins_follow_lineage_and_fetch_each_original_once(db_path):
    pages = {
        OWN: "Kind: own\n\nAcme Robotics was founded in 2014.",
        "https://copy.test/a": "Canonical: https://wire.test/story\n\n"
                               "Acme Robotics was founded in 2014.",
        "https://copy2.test/b": "Canonical: https://wire.test/story\n\n"
                                "Acme Robotics was founded in 2014.",
        "https://wire.test/story": "Registrant: wire.test\n\nNo company facts here.",
        "https://empty.test/c": "Canonical: https://never.test/x\n\nNothing about it.",
    }
    web = FakeWeb(pages=pages, hidden={"https://wire.test/story"})
    with open_app(db_path, web) as c:
        c.post("/_test/reset", json={"now": T1, "users": USERS})
        field = build(c, login(c))["fields"]["founded_year"]
    assert field["origins"] == [DOMAIN, "wire.test"] and field["corroborated"] is True
    assert field["corroborated_since"] == T1
    assert {c["url"]: c["origin"] for c in field["candidates"]} == {
        OWN: DOMAIN, "https://copy.test/a": "wire.test", "https://copy2.test/b": "wire.test"}
    extracts = [a for m, a in web.calls if m == "extract"]
    assert extracts.count("https://wire.test/story") == 1      # one fetch per URL
    assert "https://never.test/x" not in extracts              # page without candidates
    assert len(extracts) == len(set(extracts))
    searches = [a for m, a in web.calls if m == "search"]
    assert len(searches) == len(set(searches)) == 10


def test_investors_from_an_own_page_and_history(client):
    h = login(client)
    fields = build(client, h)["fields"]
    assert list(fields)[-2:] == ["executives", "investors"]
    investors = fields["investors"]
    assert investors["value"] == ["Northwind Ventures"] and investors["status"] == "known"
    assert investors["candidates"][0]["kind"] == "own"
    history = client.get(f"/dossiers/{DOMAIN}/history", headers=h).json()["fields"]
    assert [e["type"] for e in history["investors"]] == ["initial"]


# --------------------------------------------------------------------------- restarts

def test_a_build_in_flight_at_a_stop_ends_failed_with_its_spend(db_path):
    web = FakeWeb(pages={OWN: "Kind: own\n\nAcme Robotics was founded in 2014."}, delay=0.3)
    with open_app(db_path, web) as c:
        c.post("/_test/reset", json={"now": T1, "users": USERS})
        h = login(c)
        body = batch(c, h, {"domains": [DOMAIN], "budget_units": 60}).json()
        time.sleep(0.1)   # the searches have reserved and are in flight
        with open_app(db_path, FakeWeb()) as again:   # a new process on the same file
            dossier = again.get(f"/dossiers/{DOMAIN}", headers=h).json()
            assert dossier["state"] == "failed" and dossier["fields"]["ceo"]["value"] is None
            assert 0 < dossier["spent_units"] <= 60
            done = again.get(f"/batches/{body['batch_id']}", headers=h).json()
            assert done["state"] == "done"
            assert done["spent_units"] == dossier["spent_units"] <= 60
            r = again.post(f"/dossiers/{DOMAIN}/refresh", headers={**h, "Idempotency-Key": "r"})
            assert r.status_code == 202


def test_batches_survive_a_restart(client, web, db_path):
    h = login(client)
    body = batch(client, h, {"domains": ["one.test"], "budget_units": 40}).json()
    done = wait(client, h, f"/batches/{body['batch_id']}")
    export = client.get("/_test/export").json()
    client.close()
    with open_app(db_path, web) as again:
        assert again.get(f"/batches/{body['batch_id']}", headers=h).json() == done
        assert again.get("/_test/export").json() == export
        replay = batch(again, h, {"domains": ["one.test"], "budget_units": 40})
        assert replay.status_code == 200 and replay.json() == body


# --------------------------------------------------------------------------- upgrades

def test_stage3_export_upgrades_with_investors_unknown_and_origins(client, web):
    assert client.post("/_test/import", json=STAGE3["export"]).status_code == 204
    h = {"Authorization": f"Bearer {STAGE3['token']}"}
    now = client.get(f"/dossiers/{DOMAIN}", headers=h).json()
    assert now["fields"]["ceo"]["value"] == "Lee Park"
    assert now["fields"]["investors"]["status"] == "unknown"
    assert all(c["origin"] == c["url"].split("/")[2] for f in now["fields"].values()
               for c in f["candidates"])
    founded = now["fields"]["founded_year"]
    assert founded["origins"] == ["acme-robotics.test", "bizdata.test"]
    assert founded["corroborated"] and founded["corroborated_since"] == T1
    then = client.get(f"/dossiers/{DOMAIN}?as_of={T1}", headers=h).json()
    assert then["fields"]["ceo"]["value"] == "Dana Ruiz"
    assert then["fields"]["investors"]["value"] is None
    values = client.get(f"/dossiers/{DOMAIN}/values?true_at=2025-06-01",
                        headers=h).json()["fields"]
    assert values["ceo"]["value"] == "Dana Ruiz" and "origins" in values["ceo"]
    history = client.get(f"/dossiers/{DOMAIN}/history", headers=h).json()["fields"]
    assert history["investors"] == [] and len(history["ceo"]) == 2
    assert client.get("/changes", headers=h).json()["changes"] == STAGE3["export"]["state"]["feed"]
    # the first build after the upgrade adds investors as a change
    client.post(f"/dossiers/{DOMAIN}/refresh", headers={**h, "Idempotency-Key": "after"})
    wait(client, h, f"/dossiers/{DOMAIN}")
    changes = client.get("/changes", headers=h).json()["changes"]
    assert ("investors", "change") in [(c["field"], c["type"]) for c in changes]


def test_stage4_round_trip_and_invalid_origin(client, web):
    h = login(client)
    build(client, h)
    batch_id = batch(client, h, {"domains": ["one.test"], "budget_units": 40}).json()["batch_id"]
    wait(client, h, f"/batches/{batch_id}")
    export = client.get("/_test/export").json()
    assert client.post("/_test/import", json=export).status_code == 204
    assert client.get("/_test/export").json() == export
    bad = json.loads(json.dumps(export))
    d = next(d for d in bad["state"]["dossiers"] if d["domain"] == DOMAIN)
    for fields in (d["fields"], d["builds"][-1]["fields"]):
        fields["founded_year"]["candidates"][0]["origin"] = "not a domain"
    r = client.post("/_test/import", json=bad)
    assert r.status_code == 422 and client.get("/_test/export").json() == export
