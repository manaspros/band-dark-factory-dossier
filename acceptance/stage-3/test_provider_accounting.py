"""Provider accounting and 429 behavior visible in the optional mock log."""
from __future__ import annotations

import time

import pytest

from conftest import API, TEST_DOMAIN, create_build, wait_dossier


def test_build_budget_and_research_domain_search(mock_admin, api: API, token: str) -> None:
    """T75 and carried Stage 1/2 rules: provider spend is capped and exact search is singular."""
    if not mock_admin.enabled:
        pytest.skip("provider accounting needs DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.reset()
    dossier, _ = create_build(api, token, key="s3-budget-observable")
    calls = mock_admin.calls()
    assert sum(call["cost"] for call in calls) <= 80
    assert dossier["spent_units"] == sum(call["cost"] for call in calls)
    domain_searches = [call for call in calls if call.get("method") == "search"
                       and call.get("query") == TEST_DOMAIN and call["status"] < 400]
    assert len(domain_searches) == 1, domain_searches


def test_429_is_free_and_retried_after_rate_limit_interval(mock_admin, api: API,
                                                            token: str) -> None:
    """Carried Stage 1/2 ruling: three 429 retries, each spaced by at least one second."""
    if not mock_admin.enabled:
        pytest.skip("429 call accounting needs DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.reset()
    mock_admin.fault("nimble", ["search"], "rate_limit")
    domain = "stage3-rate-limit.test"
    response = api.post("/dossiers", token=token,
                        headers={"Idempotency-Key": "s3-rate-limit"},
                        json={"domain": domain})
    assert response.status_code == 202, response.text
    observed: dict[int, float] = {}
    deadline = time.monotonic() + 300
    calls = []
    while time.monotonic() < deadline:
        calls = [c for c in mock_admin.calls() if c.get("method") == "search"
                 and c.get("query") == domain and c.get("provider") == "nimble"]
        for count in range(1, len(calls) + 1):
            observed.setdefault(count, time.monotonic())
        if calls and calls[-1]["status"] < 400:
            break
        state_response = api.get(f"/dossiers/{domain}", token=token)
        if state_response.status_code == 200 and state_response.json()["state"] in ("ready", "failed"):
            break
        time.sleep(0.05)
    assert [call["status"] for call in calls] == [429, 429, 429, 200], calls
    assert all(call["cost"] == 0 for call in calls[:3])
    assert calls[3]["cost"] > 0
    assert all(observed[n + 1] - observed[n] >= 0.9 for n in (1, 2, 3)), observed


def test_non_429_refused_exact_domain_search_is_bounded_and_build_survives(
        mock_admin, api: API, token: str) -> None:
    """Carried Stage 1 rule: three exact-domain attempts; provider refusals cost nothing."""
    if not mock_admin.enabled:
        pytest.skip("provider refusal accounting needs DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.reset()
    mock_admin.fault("nimble", ["search"], "error")
    domain = "stage3-provider-refusal.test"
    response = api.post("/dossiers", token=token,
                        headers={"Idempotency-Key": "s3-provider-refusal"},
                        json={"domain": domain})
    assert response.status_code == 202, response.text
    dossier = wait_dossier(api, token, domain, timeout=120)
    assert dossier["state"] in ("ready", "failed")
    exact = [c for c in mock_admin.calls() if c.get("provider") == "nimble"
             and c.get("method") == "search" and c.get("query") == domain]
    assert 1 <= len(exact) <= 3, exact
    assert all(c["status"] >= 400 and c["cost"] == 0 for c in exact)
