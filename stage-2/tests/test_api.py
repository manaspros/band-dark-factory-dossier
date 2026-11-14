"""End-to-end API behaviour through Starlette's TestClient with a fake provider."""
import time

import pytest
from starlette.testclient import TestClient

from app.main import create_app
from tests.fakes import DOMAIN, FakeWeb

FIXTURE = {"now": "2026-03-01T09:00:00+00:00",
           "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
                      "display_name": "Ada"},
                     {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
                      "display_name": "Bob"}]}


@pytest.fixture
def web():
    return FakeWeb()


@pytest.fixture
def client(web):
    with TestClient(create_app(web_factory=lambda: web)) as c:
        assert c.post("/_test/reset", json=FIXTURE).status_code == 204
        yield c


def login(client, email="ada@example.com"):
    r = client.post("/auth/login", json={"email": email, "password": "correct horse"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def wait_built(client, headers, domain=DOMAIN):
    for _ in range(200):
        body = client.get(f"/dossiers/{domain}", headers=headers).json()
        if body["state"] != "building":
            return body
        time.sleep(0.02)
    raise AssertionError("build did not finish")


def post(client, headers, domain=DOMAIN, key="k1"):
    return client.post("/dossiers", json={"domain": domain}, headers={**headers,
                                                                         "Idempotency-Key": key})


def test_health_and_errors(client):
    r = client.get("/health")
    assert r.json() == {"status": "ok"}
    assert r.headers["content-type"] == "application/json; charset=utf-8"
    assert client.get("/nope").json()["error"]["code"] == "not_found"
    assert client.delete("/health").status_code == 405


def test_seeded_login_and_signup(client):
    r = client.post("/auth/login", json={"email": "ADA@example.com", "password": "correct horse"})
    assert r.json()["user_id"] == "u_ada"
    r = client.post("/auth/signup", json={"email": "ada@example.com", "password": "12345678",
                                          "display_name": "A"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    r = client.post("/auth/signup", json={"email": "c@x.test", "password": "1234567",
                                          "display_name": "C"})
    assert r.status_code == 422
    r = client.post("/auth/signup", json={"email": "c@x.test", "password": 12345678,
                                          "display_name": "C"})
    assert r.status_code == 400
    r = client.post("/auth/signup", content=b"{", headers={"content-type": "application/json"})
    assert r.json()["error"]["code"] == "malformed_request"
    r = client.post("/auth/signup", json={"email": "c@x.test", "password": "12345678",
                                          "display_name": "C", "extra": 1})
    assert r.status_code == 201
    assert client.get("/dossiers", headers={"Authorization": f"Bearer {r.json()['token']}"}
                      ).status_code == 200


def test_auth_required_before_idempotency_key(client):
    r = client.post("/dossiers", json={"domain": DOMAIN})
    assert r.status_code == 401
    assert client.get("/dossiers", headers={"Authorization": "bearer x"}).status_code == 401


def test_build_and_read(client, web):
    h = login(client)
    r = post(client, h, "Acme-Robotics.TEST.")
    assert r.status_code == 202
    assert r.json()["domain"] == DOMAIN and r.json()["state"] == "building"
    body = wait_built(client, h, "www.acme-robotics.test")
    assert body["state"] == "ready"
    assert body["researched_at"] == "2026-03-01T09:00:00+00:00"
    f = body["fields"]
    assert f["founded_year"]["value"] == 2014
    assert f["hq_city"]["value"] == "Lisbon"
    assert f["ceo"]["value"] == "Dana Ruiz"
    assert f["funding_total"]["value"] == 12000000
    assert f["headcount_range"]["value"] == "51-200"
    assert f["legal_name"] == {"value": None, "status": "unknown", "citations": [],
                               "candidates": []}
    assert f["ceo"]["status"] == "known"
    ceo = f["ceo"]["candidates"]
    assert ceo == [{"value": "Dana Ruiz", "url": "https://acme-robotics.test/about",
                    "excerpt": "Dana Ruiz has led Acme Robotics as chief executive since 2021.",
                    "provider": "nimble", "kind": "own", "published_at": None,
                    "retrieved_at": "2026-03-01T09:00:00+00:00", "selected": True}]
    assert web.count("research") == 1      # research runs on every build
    assert body["spent_units"] == 8 + 25 + 2 * 3   # searches, research, two rendered pages
    assert web.calls.count(("search", DOMAIN)) == 1
    assert post(client, h, key="k2").status_code == 200


def test_idempotency(client, web):
    h = login(client)
    first = post(client, h)
    assert post(client, h).status_code == 200 and post(client, h).json() == first.json()
    r = client.post("/dossiers", json={"domain": "ACME-robotics.test"},
                    headers={**h, "Idempotency-Key": "k1"})
    assert r.status_code == 409
    r = client.post("/dossiers", json={"domain": 5}, headers={**h, "Idempotency-Key": "k1"})
    assert r.status_code == 409
    r = client.post("/dossiers", json={"domain": DOMAIN}, headers=h)
    assert r.json()["error"]["code"] == "missing_idempotency_key"
    r = client.post("/dossiers", json={"domain": DOMAIN}, headers={**h, "Idempotency-Key": "x" * 256})
    assert r.status_code == 422
    r = client.post("/dossiers", json={"domain": "bad"}, headers={**h, "Idempotency-Key": "k9"})
    assert r.status_code == 422
    r = client.post("/dossiers", json={"domain": "b.test"}, headers={**h, "Idempotency-Key": "k9"})
    assert r.status_code == 202                      # a key that failed with 4xx is free
    wait_built(client, h)
    calls = len(web.calls)
    refresh = client.post(f"/dossiers/{DOMAIN}/refresh", headers={**h, "Idempotency-Key": "k1"})
    assert refresh.status_code == 202                # same key, other path: a first use
    wait_built(client, h)
    replay = client.post(f"/dossiers/{DOMAIN}/refresh", content=b"not json",
                         headers={**h, "Idempotency-Key": "k1"})
    assert replay.status_code == 200 and replay.json() == refresh.json()
    assert post(client, h).json() == first.json()
    bob = login(client, "bob@example.com")
    assert post(client, bob).status_code == 200      # bob's k1 is his own
    assert len(web.calls) > calls


def test_list_and_paging(client):
    h = login(client)
    for i, d in enumerate(["b.test", "a.test", "c.test"]):
        post(client, h, d, key=f"k{i}")
    r = client.get("/dossiers?limit=2&offset=0&zzz=1", headers=h).json()
    assert [d["domain"] for d in r["dossiers"]] == ["a.test", "b.test"] and r["has_more"]
    for bad in ("limit=0", "limit=201", "limit=+4", "offset=-1", "limit=4.0", "limit=1e9"):
        assert client.get(f"/dossiers?{bad}", headers=h).status_code == 422
    assert client.get("/dossiers?q=B.TE", headers=h).json()["dossiers"][0]["domain"] == "b.test"


def test_clock(client):
    assert client.post("/_test/clock", json={"now": "2026-03-01T08:00:00+00:00"}).status_code == 422
    assert client.post("/_test/clock", json={"now": "2026-03-01T10:00:00"}).status_code == 422
    assert client.post("/_test/clock", json={"now": "2026-03-01T11:00:00+02:00"}).status_code == 204


def test_reset_rejects_shared_email_and_long_id(client):
    bad = {"now": FIXTURE["now"], "users": [FIXTURE["users"][0], {**FIXTURE["users"][1],
                                                                  "email": "ADA@example.com"}]}
    assert client.post("/_test/reset", json=bad).status_code == 422
    long_id = {"now": FIXTURE["now"], "users": [{**FIXTURE["users"][0], "id": "u" * 65}]}
    assert client.post("/_test/reset", json=long_id).status_code == 422
    assert client.post("/_test/reset", json={"users": []}).status_code == 422
    login(client, "bob@example.com")                 # nothing changed


def test_export_import_round_trip(client):
    h = login(client)
    first = post(client, h)
    wait_built(client, h)
    exported = client.get("/_test/export").json()
    assert exported["track"] == "dossier" and exported["format_version"] == 1
    assert "correct horse" not in str(exported)
    assert client.post("/_test/reset", json={"now": FIXTURE["now"], "users": []}).status_code == 204
    assert client.get("/dossiers", headers=h).status_code == 401
    assert client.post("/_test/import", json=exported).status_code == 204
    assert client.post("/_test/import", json=exported).status_code == 204
    assert client.get("/_test/export").json() == exported
    assert post(client, h).json() == first.json()    # old token and replay still work
    login(client)                                    # login still works; adds a token
    exported = client.get("/_test/export").json()
    for bad in ({**exported, "track": "x"}, {**exported, "format_version": True},
                {k: v for k, v in exported.items() if k != "state"}):
        assert client.post("/_test/import", json=bad).status_code == 422
    assert client.get("/_test/export").json() == exported


def test_huge_integer_query_parameter_is_422(client):
    h = login(client)
    r = client.get("/dossiers?limit=" + "9" * 5000, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert client.get("/dossiers?offset=" + "1" * 5000, headers=h).status_code == 200


def test_clock_needs_full_rfc3339(client):
    for bad in ("2026-03-01T09:30+00:00", "2026-03-01 09:30:00+00:00", "2026-03-01T09:30:00",
                "20260301T093000+00:00", "2026-03-01T09:30:00+0000", 5):
        r = client.post("/_test/clock", json={"now": bad})
        assert r.status_code in (400, 422), bad
    for good in ("2026-03-01T09:30:00Z", "2026-03-01t09:30:00.25z", "2026-03-01T11:30:00.5+02:00"):
        assert client.post("/_test/clock", json={"now": good}).status_code == 204, good


def test_import_with_wrong_types_is_422_and_changes_nothing(client):
    exported = client.get("/_test/export").json()

    def with_state(**changes):
        return {**exported, "state": {**exported["state"], **changes}}

    for bad in (with_state(tokens=[{"token_sha256": "a", "user_id": []}]),
                with_state(tokens=[{"token_sha256": "a", "user_id": {}}]),
                with_state(idempotency=[{"user_id": [], "method": "POST", "path": "/dossiers",
                                         "key": "k", "fingerprint": "{}", "status": 202,
                                         "body": {}}]),
                with_state(dossiers=[{"dossier_id": "d_1", "domain": "not a domain",
                                      "state": "ready", "fields": {}, "researched_at": None,
                                      "spent_units": 0}]),
                with_state(users=[{"id": ["x"]}])):
        r = client.post("/_test/import", json=bad)
        assert r.status_code == 422, r.text
    assert client.get("/_test/export").json() == exported


def test_deeply_nested_body_is_400(client):
    h = login(client)
    deep = b"[" * 100_000 + b"]" * 100_000
    for path, headers in (("/auth/signup", {}), ("/_test/import", {}),
                          ("/dossiers", {**h, "Idempotency-Key": "deep"})):
        r = client.post(path, content=deep, headers={"content-type": "application/json", **headers})
        assert r.status_code == 400, (path, r.status_code)
