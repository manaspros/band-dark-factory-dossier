"""Stage-3 endpoints end to end: fields with times, history, feed, as_of, values, upgrades
and restarts (T8-T11, T25-T74), through the TestClient with a fake provider."""
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
STAGE1 = json.loads((FIXTURES / "stage1-export.json").read_text())
STAGE2 = json.loads((FIXTURES / "stage2-export.json").read_text())
T1, T2, T3 = ("2026-03-01T09:00:00+00:00", "2026-04-01T09:00:00+00:00",
              "2026-05-01T09:00:00+00:00")
USERS = [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
          "display_name": "Ada"}]
ABOUT = "https://acme-robotics.test/about"
TEAM = "https://acme-robotics.test/team"


def about(effective, ceo):
    return (f"Kind: own\nEffective: {effective}\n\n"
            f"Acme Robotics was founded in 2014. {ceo} is the chief executive officer of "
            "Acme Robotics.")


FIRST_PAGES = {ABOUT: about("2021-04-01", "Dana Ruiz"),
               TEAM: "Kind: own\nEffective: 2025-09-01\n\n"
                     "Ana Silva is the chief financial officer of Acme Robotics."}


def open_app(path, web):
    services = Services(store=Store(Database(str(path))))
    return TestClient(create_app(services, web_factory=lambda: web))


@pytest.fixture
def web():
    return FakeWeb(pages=FIRST_PAGES)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "dossier.db"


@pytest.fixture
def client(web, db_path):
    with open_app(db_path, web) as c:
        assert c.post("/_test/reset", json={"now": T1, "users": USERS}).status_code == 204
        yield c


def login(client):
    r = client.post("/auth/login", json={"email": "ada@example.com", "password": "correct horse"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def wait_built(client, h, domain=DOMAIN):
    for _ in range(300):
        body = client.get(f"/dossiers/{domain}", headers=h).json()
        if body["state"] != "building":
            return body
        time.sleep(0.02)
    raise AssertionError("build did not finish")


def build(client, h, now=None, domain=DOMAIN, key=None):
    if now:
        assert client.post("/_test/clock", json={"now": now}).status_code == 204
    if domain in client.get("/dossiers", headers=h).text:
        r = client.post(f"/dossiers/{domain}/refresh",
                        headers={**h, "Idempotency-Key": key or f"r-{now}"})
    else:
        r = client.post("/dossiers", json={"domain": domain},
                        headers={**h, "Idempotency-Key": key or "create"})
    assert r.status_code in (200, 202), r.text
    return wait_built(client, h, domain)


def get(client, h, path):
    r = client.get(path, headers=h)
    return r.status_code, r.json()


def three_builds(client, web):
    """Dana Ruiz (2021-04-01) -> Lee Park from 2026-03-20 (change) -> Kim Lee from
    2026-03-01 (correction); Ana Silva CFO throughout."""
    h = login(client)
    build(client, h)
    web.pages[ABOUT] = about("2026-03-20", "Lee Park")
    build(client, h, T2)
    web.pages[ABOUT] = about("2026-03-01", "Kim Lee")
    build(client, h, T3)
    return h


def test_fields_carry_times_and_executives(client):
    h = login(client)
    body = build(client, h)
    fields = body["fields"]
    assert list(fields) == ["legal_name", "hq_city", "ceo", "founded_year", "headcount_range",
                            "funding_total", "executives"]
    assert fields["ceo"]["true_from"] == "2021-04-01" and fields["ceo"]["learned_at"] == T1
    assert fields["legal_name"]["true_from"] is None and fields["legal_name"]["learned_at"] is None
    ex = fields["executives"]
    assert ex["value"] == [{"title": "cfo", "name": "Ana Silva"}]
    assert ex["status"] == "known" and ex["true_from"] == "2025-09-01"
    assert ex["candidates"][0]["title"] == "cfo" and ex["candidates"][0]["learned_at"] == T1
    assert ex["citations"] == [{"url": TEAM, "provider": "nimble", "excerpt":
                                "Ana Silva is the chief financial officer of Acme Robotics."}]


def test_history_and_feed_change_then_correction(client, web):
    h = three_builds(client, web)
    _, hist = get(client, h, f"/dossiers/{DOMAIN}/history")
    assert list(hist["fields"]) == ["legal_name", "hq_city", "ceo", "founded_year",
                                    "headcount_range", "funding_total", "executives"]
    assert [(e["type"], e["value"], e["true_from"], e["learned_at"])
            for e in hist["fields"]["ceo"]] == [
        ("initial", "Dana Ruiz", "2021-04-01", T1), ("change", "Lee Park", "2026-03-20", T2),
        ("correction", "Kim Lee", "2026-03-01", T3)]
    assert [e["type"] for e in hist["fields"]["founded_year"]] == ["initial"]
    assert [e["type"] for e in hist["fields"]["executives"]] == ["initial"]
    assert hist["fields"]["legal_name"] == []
    _, feed = get(client, h, "/changes")
    assert feed == {"has_more": False, "changes": [
        {"seq": 1, "domain": DOMAIN, "field": "ceo", "type": "change", "from": "Dana Ruiz",
         "to": "Lee Park", "true_from": "2026-03-20", "learned_at": T2},
        {"seq": 2, "domain": DOMAIN, "field": "ceo", "type": "correction", "from": "Lee Park",
         "to": "Kim Lee", "true_from": "2026-03-01", "learned_at": T3}]}
    # the same selected value adds nothing, even with new true_from
    web.pages[ABOUT] = about("2026-02-01", "Kim Lee")
    build(client, h, "2026-06-01T09:00:00+00:00")
    assert len(get(client, h, "/changes")[1]["changes"]) == 2
    assert get(client, h, f"/dossiers/{DOMAIN}")[1]["fields"]["ceo"]["learned_at"] == T3


def test_failed_build_adds_nothing_but_counts_spend(client, web):
    h = login(client)
    first = build(client, h)
    web.refuse = lambda m, a, n: True
    body = build(client, h, T2)
    assert body["state"] == "failed" and body["fields"] == first["fields"]
    assert get(client, h, "/changes")[1]["changes"] == []
    _, at = get(client, h, f"/dossiers/{DOMAIN}?as_of={T2}")
    assert at["state"] == "ready" and at["researched_at"] == T1
    assert at["spent_units"] == body["spent_units"]


def test_executives_unknown_until_first_value_gives_change(client, web):
    web.pages.pop(TEAM)
    h = login(client)
    build(client, h)
    web.pages[TEAM] = "Acme Robotics CTO: Ben Okafor."
    build(client, h, T2)
    _, feed = get(client, h, "/changes")
    assert [(c["field"], c["type"], c["from"], c["to"]) for c in feed["changes"]] == [
        ("executives", "change", None, [{"title": "cto", "name": "Ben Okafor"}])]
    _, hist = get(client, h, f"/dossiers/{DOMAIN}/history")
    assert [e["type"] for e in hist["fields"]["executives"]] == ["change"]


def test_as_of(client, web):
    h = three_builds(client, web)
    base = f"/dossiers/{DOMAIN}?as_of="
    assert get(client, h, base + "2026-02-28T23:59:59Z")[0] == 404
    status, at = get(client, h, base + "2026-03-31T00:00:00%2B00:00")
    assert status == 200 and at["fields"]["ceo"]["value"] == "Dana Ruiz"
    assert at["researched_at"] == T1 and at["state"] == "ready"
    assert at["fields"]["ceo"]["learned_at"] == T1
    status, at = get(client, h, base + "2026-04-01T10:00:00+01:00")   # = T2, plus kept as +
    assert status == 200 and at["fields"]["ceo"]["value"] == "Lee Park"
    assert get(client, h, base + "2026-03-01T09:00:00")[0] == 422
    assert get(client, h, base + "yesterday")[0] == 422
    assert get(client, h, "/dossiers/nope.test?as_of=" + T1)[0] == 404
    assert get(client, h, f"/dossiers/{DOMAIN}")[1]["fields"]["ceo"]["value"] == "Kim Lee"


def test_values_at_dates(client, web):
    h = three_builds(client, web)
    base = f"/dossiers/{DOMAIN}/values?true_at="
    status, body = get(client, h, base + "2025-06-01")
    assert status == 200 and body["domain"] == DOMAIN and body["true_at"] == "2025-06-01"
    assert body["as_of"] == T3                                     # the clock's now
    assert body["fields"]["ceo"]["value"] == "Dana Ruiz"
    assert body["fields"]["ceo"]["true_from"] == "2021-04-01"
    assert body["fields"]["executives"]["value"] is None       # Ana Silva from 2025-09-01
    later = get(client, h, base + "2026-03-10")[1]["fields"]
    assert later["ceo"]["value"] == "Kim Lee"
    assert later["executives"] == {"value": [{"title": "cfo", "name": "Ana Silva"}],
                                   "true_from": "2025-09-01", "citations": [
                                       {"url": TEAM, "provider": "nimble", "excerpt":
                                        "Ana Silva is the chief financial officer of "
                                        "Acme Robotics."}]}
    # with what was known at T2 only, Lee Park held from 2026-03-20
    known_t2 = get(client, h, base + "2026-03-25&as_of=" + T2)[1]
    assert known_t2["fields"]["ceo"]["value"] == "Lee Park" and known_t2["as_of"] == T2
    assert get(client, h, base + "2026-03-10&as_of=" + T2)[1]["fields"]["ceo"]["value"] \
        == "Dana Ruiz"
    empty = get(client, h, base + "2000-01-01")[1]["fields"]["ceo"]
    assert empty == {"value": None, "true_from": None, "citations": []}
    assert get(client, h, base + "2025-6-1")[0] == 422
    assert get(client, h, f"/dossiers/{DOMAIN}/values")[0] == 422
    assert get(client, h, base + "2025-06-01&as_of=2026-01-01")[0] == 422
    assert get(client, h, base + "2025-06-01&as_of=2026-01-01T00:00:00Z")[0] == 404
    assert get(client, h, "/dossiers/nope.test/values?true_at=2025-06-01")[0] == 404


def test_changes_paging_and_auth(client, web):
    h = three_builds(client, web)
    assert get(client, h, "/changes?limit=1")[1]["has_more"] is True
    page = get(client, h, "/changes?since=1&limit=1")[1]
    assert [c["seq"] for c in page["changes"]] == [2] and page["has_more"] is False
    assert get(client, h, "/changes?since=2")[1] == {"changes": [], "has_more": False}
    for bad in ("since=-1", "since=1e3", "limit=0", "limit=201", "limit=x"):
        assert get(client, h, f"/changes?{bad}")[0] == 422, bad
    assert client.get("/changes").status_code == 401
    assert client.get(f"/dossiers/{DOMAIN}/history").status_code == 401
    assert client.get(f"/dossiers/{DOMAIN}/values?true_at=2025-01-01").status_code == 401
    assert get(client, h, "/dossiers/nope.test/history")[0] == 404
    assert get(client, h, "/dossiers/bad_domain/history")[0] == 422


def test_concurrent_refreshes_run_one_build_and_add_entries_once(client, web):
    h = login(client)
    build(client, h)
    web.pages[ABOUT] = about("2026-03-20", "Lee Park")
    web.delay = 0.05
    client.post("/_test/clock", json={"now": T2})
    for i in range(10):
        r = client.post(f"/dossiers/{DOMAIN}/refresh", headers={**h, "Idempotency-Key": f"c{i}"})
        assert r.status_code == 202
    wait_built(client, h)
    assert web.count("research") == 2
    assert [c["seq"] for c in get(client, h, "/changes")[1]["changes"]] == [1]


# --------------------------------------------------------------------------- restarts

ENDPOINTS = [f"/dossiers/{DOMAIN}", f"/dossiers/{DOMAIN}?as_of={T2}",
             f"/dossiers/{DOMAIN}/values?true_at=2026-03-25",
             f"/dossiers/{DOMAIN}/values?true_at=2025-01-01&as_of={T1}",
             f"/dossiers/{DOMAIN}/history", "/dossiers", "/changes"]


def test_state_survives_a_restart(client, web, db_path):
    h = three_builds(client, web)
    replay = client.post(f"/dossiers/{DOMAIN}/refresh", headers={**h, "Idempotency-Key": "idem"})
    wait_built(client, h)
    before = {path: get(client, h, path) for path in ENDPOINTS}
    export = client.get("/_test/export").json()
    client.close()
    with open_app(db_path, web) as again:                    # a new process on the same file
        assert {path: get(again, h, path) for path in ENDPOINTS} == before
        assert again.get("/_test/export").json() == export
        assert login(again)                                  # the password still signs in
        r = again.post(f"/dossiers/{DOMAIN}/refresh", headers={**h, "Idempotency-Key": "idem"})
        assert r.status_code == 200 and r.json() == replay.json()
        web.pages[ABOUT] = about("2026-06-01", "Max Rao")
        assert again.post("/_test/clock", json={"now": "2026-02-01T00:00:00Z"}).status_code \
            == 422                                           # the clock still reads T3
        body = build(again, h, "2026-07-01T00:00:00+00:00")
        assert body["fields"]["ceo"]["value"] == "Max Rao"
        assert [c["seq"] for c in get(again, h, "/changes")[1]["changes"]] == [1, 2, 3]


def test_a_build_cut_short_by_a_restart_leaves_nothing(client, web, db_path):
    h = login(client)
    web.delay = 0.3
    assert client.post("/dossiers", json={"domain": DOMAIN},
                       headers={**h, "Idempotency-Key": "k"}).status_code == 202
    with open_app(db_path, web) as again:       # started while the first build still runs
        body = again.get(f"/dossiers/{DOMAIN}", headers=h).json()
        assert body["state"] == "failed" and body["fields"]["ceo"]["value"] is None
        assert again.get(f"/dossiers/{DOMAIN}/history", headers=h).json()["fields"]["ceo"] == []


# --------------------------------------------------------------------------- upgrades

def import_(client, export):
    r = client.post("/_test/import", json=export)
    assert r.status_code == 204, r.text


def test_stage1_import_is_one_ready_build_at_researched_at(client, web):
    import_(client, STAGE1["export"])
    h = {"Authorization": f"Bearer {STAGE1['token']}"}
    domain = "halvorsen-robotics.test"
    _, now = get(client, h, f"/dossiers/{domain}")
    _, hist = get(client, h, f"/dossiers/{domain}/history")
    with_value = [n for n, f in now["fields"].items() if f["value"] is not None]
    assert with_value and all(
        [(e["type"], e["true_from"], e["learned_at"]) for e in hist["fields"][n]] ==
        [("initial", None, now["researched_at"])] for n in with_value)
    assert now["fields"]["executives"]["status"] == "unknown"
    assert hist["fields"]["executives"] == []
    assert all(c["learned_at"] == c["retrieved_at"] for f in now["fields"].values()
               for c in f["candidates"])
    status, at = get(client, h, f"/dossiers/{domain}?as_of={now['researched_at']}")
    assert status == 200 and at["fields"] == now["fields"]
    assert get(client, h, f"/dossiers/{domain}?as_of=2000-01-01T00:00:00Z")[0] == 404
    values = get(client, h, f"/dossiers/{domain}/values?true_at=2026-01-01")[1]["fields"]
    assert all(v == {"value": None, "true_from": None, "citations": []} for v in values.values())
    assert get(client, h, "/changes")[1]["changes"] == []


def test_stage1_null_researched_at_has_no_ready_build_until_one_completes(client, web):
    import_(client, STAGE1["export"])
    h = {"Authorization": f"Bearer {STAGE1['token']}"}
    domain = "ferncliff-foods.test"
    _, now = get(client, h, f"/dossiers/{domain}")
    spent = now["spent_units"]
    for as_of in ("2000-01-01T00:00:00Z", "2999-01-01T00:00:00Z"):
        assert get(client, h, f"/dossiers/{domain}?as_of={as_of}")[0] == 404
        assert get(client, h, f"/dossiers/{domain}/values?true_at=2025-01-01"
                              f"&as_of={as_of}")[0] == 404
    web.pages = {"https://ferncliff-foods.test/about":
                 "Ferncliff Foods was founded in 1990. Ana Silva is CFO of Ferncliff Foods."}
    body = build(client, h, "2026-06-01T00:00:00Z", domain=domain)
    assert body["state"] == "ready"
    _, hist = get(client, h, f"/dossiers/{domain}/history")
    assert [e["type"] for e in hist["fields"]["executives"]] == ["initial"]
    _, at = get(client, h, f"/dossiers/{domain}?as_of=2999-01-01T00:00:00Z")
    assert at["spent_units"] == body["spent_units"] > spent


def test_stage2_import_keeps_candidates_with_published_dates(client, web):
    import_(client, STAGE2["export"])
    h = {"Authorization": f"Bearer {STAGE2['token']}"}
    _, now = get(client, h, f"/dossiers/{DOMAIN}")
    ceo = now["fields"]["ceo"]
    assert ceo["status"] == "contested" and ceo["value"] == "Dana Ruiz"
    assert ceo["true_from"] == "2024-12-31"           # UTC date of Published (DEV-S3b)
    assert ceo["learned_at"] == now["researched_at"]
    _, hist = get(client, h, f"/dossiers/{DOMAIN}/history")
    assert hist["fields"]["ceo"][0]["true_from"] == "2024-12-31"
    values = get(client, h, f"/dossiers/{DOMAIN}/values?true_at=2025-06-01")[1]["fields"]
    assert values["ceo"]["value"] == "Dana Ruiz" and values["founded_year"]["value"] == 2014
    _, at = get(client, h, f"/dossiers/{DOMAIN}?as_of={now['researched_at']}")
    assert at["spent_units"] == now["spent_units"]
    assert get(client, h, "/dossiers/brightwater-labs.test?as_of=2999-01-01T00:00:00Z")[0] == 404
    # the first build after import compares with the imported values
    web.pages = {ABOUT: about("2026-01-01", "Lee Park")}
    build(client, h, "2026-06-01T00:00:00Z")
    changes = get(client, h, "/changes")[1]["changes"]
    assert ("ceo", "change", "Dana Ruiz", "Lee Park") in [
        (c["field"], c["type"], c["from"], c["to"]) for c in changes]


def test_stage3_round_trip_answers_the_same(client, web):
    h = three_builds(client, web)
    before = {path: get(client, h, path) for path in ENDPOINTS}
    export = client.get("/_test/export").json()
    import_(client, export)
    assert client.get("/_test/export").json() == export
    assert {path: get(client, h, path) for path in ENDPOINTS} == before


@pytest.mark.parametrize("tamper", ["candidate_value", "feed_seq", "build_number",
                                    "history_type", "fields_not_last_build", "wrong_domain"])
def test_invalid_stage3_import_is_422_with_nothing_changed(client, web, tamper):
    three_builds(client, web)
    export = client.get("/_test/export").json()
    bad = json.loads(json.dumps(export))
    d = bad["state"]["dossiers"][0]
    if tamper == "candidate_value":
        d["builds"][0]["fields"]["founded_year"]["candidates"][0]["value"] = 2015
    elif tamper == "feed_seq":
        bad["state"]["feed"][1]["seq"] = 1
    elif tamper == "build_number":
        d["builds"][1]["number"] = 5
    elif tamper == "history_type":
        d["history"]["ceo"][0]["type"] = "rumour"
    elif tamper == "fields_not_last_build":
        d["fields"] = d["builds"][0]["fields"]
    else:
        d["domain"] = "other-company.test"
    r = client.post("/_test/import", json=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert client.get("/_test/export").json() == export
