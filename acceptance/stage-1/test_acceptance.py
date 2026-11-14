"""Independent HTTP acceptance checks for the Stage 1 dossier contract."""
import concurrent.futures
import os
import re
import time
import uuid
from urllib.parse import quote

import pytest
import requests

BASE = os.environ.get("DOSSIER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
MOCK = os.environ.get("DOSSIER_MOCK_URL", "").rstrip("/")
MOCK_TOKEN = os.environ.get("DOSSIER_MOCK_TOKEN", "")
NOW = "2026-03-01T09:00:00+00:00"
DOMAIN = "acceptance-co.test"
USER = {"id": "acceptance-user", "email": "acceptance@example.test",
        "password": "acceptance passphrase", "display_name": "Acceptance"}
FIXTURE = {"now": NOW, "users": [USER]}
FIELDS = {"legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total"}


def req(method, path, *, token=None, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, BASE + path, headers=headers, timeout=12, **kwargs)


def reset_state(fixture=FIXTURE):
    response = req("POST", "/_test/reset", json=fixture)
    assert response.status_code == 204, response.text


def login():
    response = req("POST", "/auth/login", json={"email": USER["email"], "password": USER["password"]})
    assert response.status_code == 200, response.text
    return response.json()["token"]


@pytest.fixture(autouse=True)
def disposable_state():
    reset_state()


@pytest.fixture
def token():
    return login()


def key():
    return "acceptance-" + uuid.uuid4().hex


def post_dossier(token, domain=DOMAIN, idem=None, extra=None):
    body = {"domain": domain}
    if extra:
        body.update(extra)
    headers = {"Idempotency-Key": idem} if idem is not None else {}
    return req("POST", "/dossiers", token=token, headers=headers, json=body)


def wait_for_build(token, domain=DOMAIN, timeout=300):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        response = req("GET", f"/dossiers/{domain}", token=token)
        if response.status_code == 200:
            dossier = response.json()
            if dossier["state"] != "building":
                return dossier
        time.sleep(0.05)
    pytest.fail(f"build for {domain} did not settle within {timeout}s")


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    payload = response.json()
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"].get("message"), str)


def mock_call_log():
    if not MOCK or not MOCK_TOKEN:
        pytest.skip("set DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN for provider-log assertions")
    response = requests.get(MOCK + "/_mock/log", headers={"X-Mock-Admin": MOCK_TOKEN}, timeout=5)
    assert response.status_code == 200, response.text
    return response.json()["calls"]


def mock_reset():
    if not MOCK or not MOCK_TOKEN:
        pytest.skip("set DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN for provider-log assertions")
    response = requests.post(MOCK + "/_mock/reset", headers={"X-Mock-Admin": MOCK_TOKEN},
                             json={"epoch": 0}, timeout=5)
    assert response.status_code == 204, response.text


def test_domain_normalization_is_shared_by_create_read_and_refresh(token):
    """R47–R48, R135, R142–R143, R146."""
    response = post_dossier(token, "  WWW.Acceptance-Co.TEST. ", key())
    assert response.status_code == 202, response.text
    created = response.json()
    assert created["domain"] == "acceptance-co.test"
    read = req("GET", "/dossiers/www.acceptance-co.test.", token=token)
    assert read.status_code == 200 and read.json()["dossier_id"] == created["dossier_id"]
    refresh = req("POST", "/dossiers/ACCEPTANCE-CO.TEST/refresh", token=token,
                  headers={"Idempotency-Key": key()})
    assert refresh.status_code == 202, refresh.text


@pytest.mark.parametrize("domain", ["https://acceptance-co.test", "x", "a..test", "-a.test",
                                     "a-.test", "a_b.test", "a.test/path", "a" * 64 + ".test"])
def test_invalid_domain_rejected_in_body_and_path(token, domain):
    """R48, R135–R146."""
    assert_error(post_dossier(token, domain, key()), 422, "validation_failed")
    assert_error(req("GET", f"/dossiers/{quote(domain, safe='')}", token=token), 422, "validation_failed")


def test_refresh_missing_dossier_is_not_found(token):
    """R146."""
    assert_error(req("POST", "/dossiers/no-such-dossier.test/refresh", token=token,
                     headers={"Idempotency-Key": key()}), 404, "not_found")


def test_auth_precedes_missing_idempotency_key_and_invalid_body():
    """R99–R100, R108, R118."""
    assert_error(req("POST", "/dossiers", json={}), 401, "unauthenticated")
    assert_error(req("POST", "/dossiers", headers={"Idempotency-Key": ""}, json={}),
                 401, "unauthenticated")


def test_idempotency_key_absence_empty_and_length(token):
    """R103, R108."""
    assert_error(req("POST", "/dossiers", token=token, json={"domain": DOMAIN}),
                 400, "missing_idempotency_key")
    assert_error(post_dossier(token, DOMAIN, ""), 400, "missing_idempotency_key")
    assert_error(post_dossier(token, DOMAIN, "k" * 256), 422, "validation_failed")
    assert post_dossier(token, "one.test", "k").status_code == 202
    assert post_dossier(token, "two.test", "v" * 255).status_code == 202


def test_replay_uses_json_value_and_ignores_unknown_fields(token):
    """R105, R110, R113–R114."""
    idem = key()
    first = req("POST", "/dossiers", token=token, headers={"Idempotency-Key": idem},
                data=' { "unknown": 1, "domain" : "acceptance-co.test" } ')
    assert first.status_code == 202, first.text
    replay = req("POST", "/dossiers", token=token, headers={"Idempotency-Key": idem},
                 data='{"domain":"acceptance-co.test","another_unknown":true}')
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()


def test_conflict_precedes_new_body_validation_and_failed_keys_are_reusable(token):
    """R111–R112, R118–R119."""
    idem = key()
    assert post_dossier(token, "first.test", idem).status_code == 202
    assert_error(post_dossier(token, "second.test", idem), 409, "idempotency_key_reuse")
    assert_error(req("POST", "/dossiers", token=token, headers={"Idempotency-Key": idem},
                     json={"domain": "not a domain"}), 409, "idempotency_key_reuse")
    failed_key = key()
    assert_error(post_dossier(token, "bad domain", failed_key), 422, "validation_failed")
    assert post_dossier(token, "recovered.test", failed_key).status_code == 202


def test_idempotency_key_is_scoped_by_user_and_request_path(token):
    """R104, R106–R107."""
    idem = key()
    assert post_dossier(token, "same-key.test", idem).status_code == 202
    refreshed = req("POST", "/dossiers/same-key.test/refresh", token=token,
                    headers={"Idempotency-Key": idem})
    assert refreshed.status_code == 202, refreshed.text
    second = req("POST", "/auth/signup", json={"email": "second@example.test",
                   "password": "second passphrase", "display_name": "Second"})
    assert second.status_code == 201, second.text
    other_user = post_dossier(second.json()["token"], "other-user.test", idem)
    assert other_user.status_code in (200, 202), other_user.text


def test_raw_domain_spelling_is_part_of_idempotency_identity(token):
    """R47, R105–R107."""
    idem = key()
    first = post_dossier(token, "identity-spelling.test", idem)
    assert first.status_code == 202
    # These spellings normalize to one dossier, but the raw request body differs for replay.
    conflict = post_dossier(token, "www.identity-spelling.test", idem)
    assert_error(conflict, 409, "idempotency_key_reuse")
    same = post_dossier(token, "identity-spelling.test", key())
    assert same.status_code == 200 and same.json()["dossier_id"] == first.json()["dossier_id"]


def test_refresh_body_is_ignored_for_replay(token):
    """R103, R105, R110, R115."""
    assert post_dossier(token, "refresh-body.test", key()).status_code == 202
    idem = key()
    first = req("POST", "/dossiers/refresh-body.test/refresh", token=token,
                headers={"Idempotency-Key": idem}, data="not json")
    assert first.status_code == 202, first.text
    replay = req("POST", "/dossiers/refresh-body.test/refresh", token=token,
                 headers={"Idempotency-Key": idem}, json={"ignored": [1, 2]})
    assert replay.status_code == 200 and replay.json() == first.json()


def test_concurrent_identical_replays_return_one_normal_response(token):
    """R116."""
    idem = key()
    def send(_):
        return req("POST", "/dossiers", token=token, headers={"Idempotency-Key": idem},
                   json={"domain": "concurrent-idem.test"})
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(send, range(12)))
    assert sum(r.status_code == 202 for r in responses) == 1
    assert all(r.status_code in (200, 202) for r in responses)
    assert all(r.json() == responses[0].json() for r in responses)


def test_concurrent_distinct_keys_create_one_domain_dossier(token):
    """R134."""
    def send(i):
        return post_dossier(token, "one-dossier.test", f"distinct-{i}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(send, range(12)))
    assert sum(r.status_code == 202 for r in responses) == 1
    assert all(r.status_code in (200, 202) for r in responses)
    assert len({r.json()["dossier_id"] for r in responses}) == 1


def test_list_filter_order_paging_and_unknown_query(token):
    """R44, R147–R151."""
    domains = ["zeta-list.test", "alpha-list.test", "middle-list.test"]
    for domain in domains:
        assert post_dossier(token, domain, key()).status_code == 202
    all_items = req("GET", "/dossiers", token=token, params={"q": "", "ignored": "x"}).json()
    assert [d["domain"] for d in all_items["dossiers"]] == sorted(domains)
    first = req("GET", "/dossiers", token=token, params={"limit": "2"}).json()
    assert [d["domain"] for d in first["dossiers"]] == sorted(domains)[:2]
    assert first["has_more"] is True
    rest = req("GET", "/dossiers", token=token, params={"limit": "2", "offset": "2"}).json()
    assert [d["domain"] for d in rest["dossiers"]] == sorted(domains)[2:]
    assert rest["has_more"] is False
    assert req("GET", "/dossiers", token=token, params={"q": "absent-query"}).json() == {
        "dossiers": [], "has_more": False}
    match = req("GET", "/dossiers", token=token, params={"q": "ALPHA-LIST"}).json()
    assert [d["domain"] for d in match["dossiers"]] == ["alpha-list.test"]


@pytest.mark.parametrize("params", [{"limit": "0"}, {"limit": "201"}, {"limit": "+2"},
                                     {"limit": "1.0"}, {"limit": "1e2"},
                                     {"offset": "-1"}, {"offset": "1.0"}, {"offset": "x"}])
def test_list_rejects_bad_paging_syntax_and_range(token, params):
    """R151 and §5 integer query rules."""
    assert_error(req("GET", "/dossiers", token=token, params=params), 422, "validation_failed")


def test_clock_is_monotonic_and_stationary_between_calls(token):
    """R33–R40, R42, R122."""
    later = "2026-03-03T12:00:00+05:30"
    assert req("POST", "/_test/clock", json={"now": later}).status_code == 204
    assert_error(req("POST", "/_test/clock", json={"now": "2026-03-03T06:29:59Z"}),
                 422, "validation_failed")
    assert post_dossier(token, "clock-acceptance.test", key()).status_code == 202
    dossier = wait_for_build(token, "clock-acceptance.test")
    if dossier["researched_at"] is not None:
        assert dossier["researched_at"] == later


def test_reset_duplicate_email_is_atomic_and_reset_clears_state(token):
    """R28–R30, R45, R94."""
    assert post_dossier(token, "reset-old.test", key()).status_code == 202
    conflict_fixture = {"now": NOW, "users": [USER, {**USER, "id": "other", "display_name": "Other"}]}
    assert_error(req("POST", "/_test/reset", json=conflict_fixture), 422, "validation_failed")
    # Failed reset left prior bearer token and existing dossier visible.
    assert req("GET", "/dossiers/reset-old.test", token=token).status_code == 200
    reset_state()
    new_token = login()
    assert_error(req("GET", "/dossiers/reset-old.test", token=new_token), 404, "not_found")


def test_export_import_preserves_tokens_dossiers_and_completed_retries(token):
    """R45, R161–R165, R170, R174."""
    idem = key()
    created = post_dossier(token, "portable-state.test", idem)
    assert created.status_code == 202
    snapshot_response = req("GET", "/_test/export")
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot = snapshot_response.json()
    assert snapshot["track"] == "dossier" and snapshot["format_version"] == 1
    assert "state" in snapshot
    reset_state({"now": NOW, "users": []})
    imported = req("POST", "/_test/import", json=snapshot)
    assert imported.status_code == 204, imported.text
    assert req("GET", "/dossiers/portable-state.test", token=token).status_code == 200
    replay = post_dossier(token, "portable-state.test", idem)
    assert replay.status_code == 200 and replay.json() == created.json()
    assert req("GET", "/dossiers", token=token).status_code == 200
    assert login()


def test_replay_after_refresh_returns_original_body_and_starts_nothing(token):
    """R117, R121, R143, R145, R170–R174."""
    if not MOCK or not MOCK_TOKEN:
        pytest.skip("requires mock provider call log to prove replay starts no provider call")
    mock_reset()
    original_key = key()
    original = post_dossier(token, "replay-after-change.test", original_key)
    assert original.status_code == 202
    wait_for_build(token, "replay-after-change.test")
    refresh = req("POST", "/dossiers/replay-after-change.test/refresh", token=token,
                  headers={"Idempotency-Key": key()})
    assert refresh.status_code == 202
    wait_for_build(token, "replay-after-change.test")
    before = mock_call_log()
    replay = post_dossier(token, "replay-after-change.test", original_key)
    after = mock_call_log()
    assert replay.status_code == 200 and replay.json() == original.json()
    assert len(after) == len(before)


def test_import_errors_are_atomic(token):
    """R161–R167 and §5 malformed-request handling."""
    assert post_dossier(token, "preserve-import-error.test", key()).status_code == 202
    assert_error(req("POST", "/_test/import", data="{"), 400, "malformed_request")
    assert_error(req("POST", "/_test/import", json={"track": "wrong", "format_version": 1,
                     "state": {}}), 422, "validation_failed")
    assert req("GET", "/dossiers/preserve-import-error.test", token=token).status_code == 200


def test_import_repeatedly_restores_snapshot_and_reset_clears_imported_data(token):
    """R166, R175–R176."""
    assert post_dossier(token, "repeat-import.test", key()).status_code == 202
    exported = req("GET", "/_test/export").json()
    for _ in range(2):
        reset_state({"now": NOW, "users": []})
        assert req("POST", "/_test/import", json=exported).status_code == 204
        assert req("GET", "/dossiers/repeat-import.test", token=token).status_code == 200
    reset_state()
    new_token = login()
    assert_error(req("GET", "/dossiers/repeat-import.test", token=new_token), 404, "not_found")


def test_build_contract_and_citation_shape(token):
    """R1, R61–R62, R120, R126, R136–R141, R171–R182."""
    created = post_dossier(token, "halvorsen-robotics.test", key())
    assert created.status_code == 202
    initial = req("GET", "/dossiers/halvorsen-robotics.test", token=token).json()
    assert set(initial["fields"]) == FIELDS
    if initial["state"] == "building":
        for field in initial["fields"].values():
            assert field == {"value": None, "status": "unknown", "citations": []}
    dossier = wait_for_build(token, "halvorsen-robotics.test", timeout=300)
    assert set(dossier["fields"]) == FIELDS
    assert isinstance(dossier["spent_units"], int) and 0 <= dossier["spent_units"] <= 80
    assert dossier["state"] in ("ready", "failed")
    assert (dossier["researched_at"] is not None) == (dossier["state"] == "ready")
    for field in dossier["fields"].values():
        assert field["status"] == ("known" if field["value"] is not None else "unknown")
        if field["value"] is None:
            assert field["citations"] == []
        else:
            assert field["citations"]
            for citation in field["citations"]:
                assert set(citation) == {"url", "excerpt", "provider"}
                assert citation["provider"] in ("nimble", "tavily")
                assert 1 <= len(citation["excerpt"]) <= 500
                assert citation["url"].startswith(("http://", "https://"))


def test_provider_spend_and_exact_domain_search(token):
    """R1–R2, R61–R63, R152–R160; requires mock log access."""
    if not MOCK or not MOCK_TOKEN:
        pytest.skip("set DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_reset()
    assert post_dossier(token, "halvorsen-robotics.test", key()).status_code == 202
    dossier = wait_for_build(token, "halvorsen-robotics.test", timeout=300)
    calls = mock_call_log()
    assert dossier["spent_units"] == sum(call["cost"] for call in calls)
    assert dossier["spent_units"] <= 80
    successful = [c for c in calls if c["method"] == "search" and 200 <= c["status"] < 400]
    exact = [c for c in successful if c.get("query") == "halvorsen-robotics.test"]
    assert len(exact) == 1
    assert all(c["provider"] in ("nimble", "tavily") for c in calls)


def test_citations_match_provider_served_text(token):
    """R1, R61–R62, R171–R186; detailed format examples require curated corpora."""
    if not MOCK or not MOCK_TOKEN:
        pytest.skip("set DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_reset()
    assert post_dossier(token, "halvorsen-robotics.test", key()).status_code == 202
    dossier = wait_for_build(token, "halvorsen-robotics.test", timeout=300)
    calls = mock_call_log()
    served = {(c["provider"], entry["url"]): entry["text"]
              for c in calls for entry in c.get("served", [])}
    for field in dossier["fields"].values():
        for citation in field["citations"]:
            text = served.get((citation["provider"], citation["url"]))
            assert text is not None
            excerpt = re.sub(r"\s+", " ", citation["excerpt"]).strip()
            lines = text.splitlines()
            if lines and re.match(r"^[A-Z][A-Za-z-]*:", lines[0]):
                try:
                    text = "\n".join(lines[lines.index("") + 1:])
                except ValueError:
                    text = ""
            assert excerpt in re.sub(r"\s+", " ", text)
            assert not re.search(r"[.!?][\"”’)\]]?\s+", excerpt)


def test_reset_during_build_cannot_write_stale_results(token):
    """R31; needs mock admin controls to delay a provider answer."""
    if not MOCK or not MOCK_TOKEN:
        pytest.skip("requires mock admin access")
    mock_reset()
    fault = requests.post(MOCK + "/_mock/faults", headers={"X-Mock-Admin": MOCK_TOKEN},
                          json={"provider": "nimble", "methods": ["search"], "mode": "delay", "seconds": 2},
                          timeout=5)
    assert fault.status_code == 204, fault.text
    assert post_dossier(token, "stale-build.test", key()).status_code == 202
    time.sleep(0.2)
    reset_state()
    assert_error(req("GET", "/dossiers/stale-build.test", token=login()), 404, "not_found")
