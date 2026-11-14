"""Batch validation, ownership, idempotency, and shared spend (F2-F3, F55-F69)."""
from __future__ import annotations

import pytest

from conftest import API, BOB, DOMAIN, MockAdmin, create, key, wait_batch


def submit(api: API, token: str, body: object, idem: str | None = None):
    return api.post("/batches", token=token,
                    headers={"Idempotency-Key": idem or key()}, json=body)


@pytest.mark.parametrize("body", [
    {}, {"domains": [], "budget_units": 10},
    {"domains": [f"a{i}.test" for i in range(51)], "budget_units": 10},
    {"domains": ["not a domain"], "budget_units": 10},
    {"domains": ["A.test", "a.test"], "budget_units": 10},
])
def test_batch_domain_validation(api: API, token: str, body: dict) -> None:
    """F57-F60: list size, normalisation validity and duplicate checks."""
    response = submit(api, token, body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_failed"


@pytest.mark.parametrize("budget", [None, "10", True, 1.5, 0, -1, 100001])
def test_batch_budget_validation_precedence(api: API, token: str, budget) -> None:
    """F60-F63: budget_units invalid type/value always wins with 422."""
    body = {"domains": ["alpha.test"], "budget_units": budget}
    response = submit(api, token, body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_failed"


@pytest.mark.parametrize("domains", ["alpha.test", [None], [1], {"domain": "alpha.test"}])
def test_wrong_typed_domains_use_malformed_request(api: API, token: str, domains) -> None:
    """D4-9/F58: domains wrong JSON types retain the Stage 1 400 rule."""
    response = submit(api, token, {"domains": domains, "budget_units": 10})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "malformed_request"


def test_batch_idempotency_and_owner_scoping(api: API, token: str) -> None:
    """F2: same key/body replays, changed body conflicts, and another user sees 404."""
    idem = key()
    body = {"domains": ["batch-idem.test"], "budget_units": 80}
    first = submit(api, token, body, idem)
    assert first.status_code == 202, first.text
    done = wait_batch(api, token, first.json()["batch_id"])
    replay = submit(api, token, body, idem)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    conflict = submit(api, token, {"domains": ["batch-other.test"], "budget_units": 80}, idem)
    assert conflict.status_code == 409, conflict.text
    bob = api.login(BOB)
    hidden = api.get(f"/batches/{done['batch_id']}", token=bob)
    assert hidden.status_code == 404, hidden.text
    assert hidden.json()["error"]["code"] == "not_found"
    assert api.get("/batches/b_missing", token=token).status_code == 404
    assert api.get(f"/batches/{done['batch_id']}").status_code == 401


def test_concurrent_same_key_starts_one_batch(api: API, token: str) -> None:
    """F2/F57: concurrent first use with one user/key/body shares one batch identity."""
    import concurrent.futures

    idem = key()
    body = {"domains": ["batch-concurrent-s4.test"], "budget_units": 80}
    def send():
        return submit(api, token, body, idem)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: send(), range(6)))
    assert all(response.status_code in (200, 202) for response in responses), [r.text for r in responses]
    assert len({response.json()["batch_id"] for response in responses}) == 1
    assert set(responses[0].json()) == {"batch_id", "state", "budget_units", "spent_units", "dossiers"}


def test_batch_requires_idempotency_key(api: API, token: str) -> None:
    """F57: missing idempotency key is rejected before a batch starts."""
    response = api.post("/batches", token=token,
                        json={"domains": ["no-key-s4.test"], "budget_units": 80})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "missing_idempotency_key"


def test_existing_domain_is_returned_in_order_without_batch_spend(
        api: API, token: str, mock_admin: MockAdmin) -> None:
    """F64-F66: an existing dossier is not rebuilt and an all-existing batch costs zero."""
    ready, _ = create(api, token, "existing-batch.test")
    if mock_admin.enabled:
        mock_admin.reset()
    body = {"domains": ["WWW.Second-Existing.TEST.", "existing-batch.test"], "budget_units": 100}
    # Create the first item too, so both entries exercise the all-existing path.
    create(api, token, "second-existing.test")
    if mock_admin.enabled:
        mock_admin.reset()
    response = submit(api, token, body)
    assert response.status_code == 202, response.text
    initial = response.json()
    assert set(initial) == {"batch_id", "state", "budget_units", "spent_units", "dossiers"}
    assert initial["budget_units"] == 100
    expected_domains = ["second-existing.test", "existing-batch.test"]
    assert [item["domain"] for item in initial["dossiers"]] == expected_domains
    batch = wait_batch(api, token, initial["batch_id"])
    assert batch["state"] == "done"
    assert set(batch) == {"batch_id", "state", "budget_units", "spent_units", "dossiers"}
    assert batch["spent_units"] == 0
    assert [item["domain"] for item in batch["dossiers"]] == expected_domains
    assert all(item["state"] == "ready" for item in batch["dossiers"])
    current = api.get("/dossiers/existing-batch.test", token=token).json()
    assert current["dossier_id"] == ready["dossier_id"]
    if mock_admin.enabled:
        assert mock_admin.calls() == []


def test_shared_budget_and_per_build_ceiling(mock_admin: MockAdmin,
                                              api: API, token: str) -> None:
    """F3/F66-F68: shared spend is bounded and zero-call exhausted builds are ready/unknown."""
    if not mock_admin.enabled:
        pytest.skip("shared-call accounting requires DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.reset()
    body = {"domains": ["budget-a.test", "budget-b.test", "budget-c.test"],
            "budget_units": 1}
    response = submit(api, token, body)
    assert response.status_code == 202, response.text
    batch = wait_batch(api, token, response.json()["batch_id"])
    assert batch["spent_units"] <= body["budget_units"]
    calls = mock_admin.calls()
    assert sum(int(call.get("cost", 0)) for call in calls) <= body["budget_units"]
    for item in batch["dossiers"]:
        dossier = api.get(f"/dossiers/{item['domain']}", token=token)
        assert dossier.status_code == 200, dossier.text
        data = dossier.json()
        assert data["state"] in ("ready", "failed")
        assert data["spent_units"] <= 80
        if data["spent_units"] == 0 and item["state"] == "ready":
            assert all(field["value"] is None for field in data["fields"].values())
