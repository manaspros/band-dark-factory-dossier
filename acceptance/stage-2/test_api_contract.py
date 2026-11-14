"""Stage 2 API edge cases not covered by the shipped smoke checks."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

from conftest import API, ALICE, BOB, begin_dossier, new_key


def error(response: requests.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"]["code"] == code, body


def test_authentication_precedes_missing_idempotency_key(api: API) -> None:
    """Stage 1 R99; S46/S48: auth remains mandatory for JSON API requests."""
    error(api.post("/dossiers", json={"domain": "alpha.test"}), 401, "unauthenticated")
    error(api.get("/dossiers"), 401, "unauthenticated")


def test_idempotency_unknown_fields_are_ignored_and_success_replays(api: API, token: str) -> None:
    """Stage 1 R111-R121: unknown fields do not affect a same-path replay."""
    key = new_key()
    first = api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                     json={"domain": "reuse-test.test", "extra": {"ignored": True}})
    assert first.status_code == 202, first.text
    original = first.json()
    replay = api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                      json={"extra_again": 5, "domain": "reuse-test.test"})
    assert replay.status_code == 200, replay.text
    assert replay.json() == original


def test_successful_key_reuse_is_resolved_before_invalid_body_validation(api: API,
                                                                         token: str) -> None:
    """Stage 1 R121: a claimed successful key with a changed body is 409 before validation."""
    key = new_key()
    created = begin_dossier(api, token, "same-company.test", key)
    assert created.status_code == 202, created.text
    error(api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                   json={"domain": "https://invalid.test/path"}), 409,
          "idempotency_key_reuse")


def test_failed_four_xx_request_does_not_claim_key(api: API, token: str) -> None:
    """Stage 1 R122: keys from validation failures remain reusable."""
    key = new_key()
    error(api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                   json={"domain": "bad_domain"}), 422, "validation_failed")
    accepted = api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                        json={"domain": "now-valid.test"})
    assert accepted.status_code == 202, accepted.text


def test_idempotency_keys_are_scoped_by_user_and_request_path(api: API,
                                                              users: dict[str, str]) -> None:
    """Stage 1 R111-R116: caller and path are part of the idempotency identity."""
    key = new_key()
    first = begin_dossier(api, users["alice"], "alice-domain.test", key)
    assert first.status_code == 202, first.text
    # The same key under another authenticated user is a fresh use, even with a new body.
    other_user = begin_dossier(api, users["bob"], "bob-domain.test", key)
    assert other_user.status_code == 202, other_user.text
    # The same user's refresh path is independently scoped from POST /dossiers.
    refresh = api.post(f"/dossiers/alice-domain.test/refresh", token=users["alice"],
                       headers={"Idempotency-Key": key})
    assert refresh.status_code == 202, refresh.text


def test_concurrent_identical_first_uses_have_one_effect(api: API, token: str) -> None:
    """Stage 1 R116: concurrent identical writes have one normal response and replays."""
    key = new_key()

    def post() -> requests.Response:
        return api.post("/dossiers", token=token, headers={"Idempotency-Key": key},
                        json={"domain": "concurrent-idempotency.test"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: post(), range(8)))
    assert sorted(response.status_code for response in responses) == [200] * 7 + [202]
    bodies = [response.json() for response in responses]
    assert all(body == bodies[0] for body in bodies)


def test_refresh_body_is_ignored_for_replay(api: API, token: str) -> None:
    """Stage 1 R113/R114: refresh ignores any body when comparing idempotent requests."""
    start = begin_dossier(api, token, "refresh-replay.test")
    assert start.status_code == 202, start.text
    key = new_key()
    first = api.post("/dossiers/refresh-replay.test/refresh", token=token,
                     headers={"Idempotency-Key": key}, json={"anything": 1})
    assert first.status_code == 202, first.text
    replay = api.post("/dossiers/refresh-replay.test/refresh", token=token,
                      headers={"Idempotency-Key": key}, json=["ignored body"])
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()


@pytest.mark.parametrize("body", [None, {"domain": 17}, []], ids=["missing", "wrong-type", "wrong-json-shape"])
def test_request_body_errors_use_the_specified_status(api: API, token: str, body) -> None:
    """Stage 1 R80, R85-R88, R135: wrong types are malformed; missing fields validate."""
    headers = {"Idempotency-Key": new_key()}
    response = api.post("/dossiers", token=token, headers=headers,
                        json={} if body is None else body)
    if body is None:
        error(response, 422, "validation_failed")
    else:
        error(response, 400, "malformed_request")


def test_unparseable_json_body_is_malformed_request(api: API, token: str) -> None:
    """Stage 1 R80/R88: an unparseable JSON body returns 400 malformed_request."""
    response = api.post("/dossiers", token=token,
                        headers={"Idempotency-Key": new_key(),
                                 "Content-Type": "application/json"}, data="{")
    error(response, 400, "malformed_request")


def test_missing_empty_and_out_of_range_idempotency_headers(api: API, token: str) -> None:
    """Stage 1 R81, R89, R108: absent/empty and overlong keys have distinct errors."""
    error(api.post("/dossiers", token=token, json={"domain": "key-test.test"}),
          400, "missing_idempotency_key")
    error(api.post("/dossiers", token=token, headers={"Idempotency-Key": ""},
                   json={"domain": "key-test.test"}), 400, "missing_idempotency_key")
    error(api.post("/dossiers", token=token, headers={"Idempotency-Key": "k" * 256},
                   json={"domain": "key-test.test"}), 422, "validation_failed")


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "limit=1e9", "limit=4.0",
                                    "limit=+4", "offset=-1", "offset=4.0", "offset=1e9" ])
def test_list_integer_query_grammar_is_decimal_only(api: API, token: str, query: str) -> None:
    """Stage 1 R87, R90, R151: invalid limit/offset forms return 422 validation_failed."""
    error(api.get("/dossiers?" + query, token=token), 422, "validation_failed")


def test_domain_normalisation_is_shared_by_create_and_path_reads(api: API, token: str) -> None:
    """Stage 1 R49-R55: normalised aliases resolve to the same dossier."""
    response = api.post("/dossiers", token=token, headers={"Idempotency-Key": new_key()},
                        json={"domain": "  WWW.Acme-Robotics.TEST.  "})
    assert response.status_code == 202, response.text
    assert response.json()["domain"] == "acme-robotics.test"
    read = api.get("/dossiers/acme-robotics.test", token=token)
    assert read.status_code == 200, read.text
    assert read.json()["dossier_id"] == response.json()["dossier_id"]


def test_list_query_filter_order_paging_and_unknown_query(api: API, token: str) -> None:
    """Stage 1 R138-R144: q, order, limit, offset, has_more and unknown query handling."""
    domains = ("list-z.test", "list-a.test", "list-m.test")
    for domain in domains:
        response = begin_dossier(api, token, domain)
        assert response.status_code == 202, response.text

    full = api.get("/dossiers?ignored=value", token=token)
    assert full.status_code == 200, full.text
    listed = full.json()
    actual = [item["domain"] for item in listed["dossiers"]]
    expected = sorted(domains)
    assert actual == expected
    assert listed["has_more"] is False
    page = api.get("/dossiers?limit=2&offset=1", token=token).json()
    assert [item["domain"] for item in page["dossiers"]] == expected[1:]
    assert page["has_more"] is False
    filtered = api.get("/dossiers?q=LIST-A", token=token).json()
    assert [item["domain"] for item in filtered["dossiers"]] == ["list-a.test"]


def test_reset_during_build_clears_state_and_old_token(api: API, token: str) -> None:
    """Stage 1 R25/R31/R33: reset replaces state and an old build cannot repopulate it."""
    created = begin_dossier(api, token, "reset-running.test")
    assert created.status_code == 202, created.text
    reset = api.post("/_test/reset", timeout=10,
                     json={"now": "2026-03-01T10:00:00+00:00", "users": [BOB]})
    assert reset.status_code == 204, reset.text
    assert api.get("/dossiers/reset-running.test", token=api.login(BOB)).status_code == 404
    assert api.get("/dossiers", token=token).status_code == 401
    error(api.post("/dossiers", token=token, headers={"Idempotency-Key": new_key()},
                   json={"domain": "old-token.test"}), 401, "unauthenticated")
