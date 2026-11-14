"""Provider refusal/failure behavior (F70-F74)."""
from __future__ import annotations

import time

import pytest

from conftest import API, MockAdmin, create, feed, history, key, wait_dossier


def test_research_failure_falls_back_to_search_and_extract(mock_admin: MockAdmin,
                                                             api: API, token: str) -> None:
    """F72: failed research does not fail a build whose searches/extracts answer."""
    if not mock_admin.enabled:
        pytest.skip("provider fault injection requires DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.reset()
    mock_admin.fault("nimble", ["research"], "error")
    domain = "research-outage-s4.test"
    response = api.post("/dossiers", token=token, json={"domain": domain},
                        headers={"Idempotency-Key": key()})
    assert response.status_code == 202, response.text
    dossier = wait_dossier(api, token, domain, timeout=20)
    assert dossier["state"] == "ready", dossier
    calls = mock_admin.calls()
    assert any(call.get("method") == "search" and call.get("status", 500) < 400 for call in calls)
    research = [call for call in calls if call.get("method") == "research"]
    assert research and all(call.get("status", 200) >= 400 and call.get("cost", 0) == 0
                            for call in research)


def test_rate_limited_exact_domain_search_retries_and_refusals_cost_nothing(
        mock_admin: MockAdmin, api: API, token: str) -> None:
    """F70/F74: exact search is retried after 429 and each refusal is free."""
    if not mock_admin.enabled:
        pytest.skip("429 call assertions require DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.reset()
    mock_admin.fault("nimble", ["search"], "rate_limit")
    domain = "s4-rate-limit.test"
    response = api.post("/dossiers", token=token, json={"domain": domain},
                        headers={"Idempotency-Key": key()})
    assert response.status_code == 202, response.text
    exact = []
    seen_at: dict[int, float] = {}
    dossier = None
    end = time.monotonic() + 30
    while time.monotonic() < end:
        exact = [call for call in mock_admin.calls() if call.get("provider") == "nimble"
                 and call.get("method") == "search" and call.get("query") == domain]
        for count in range(1, len(exact) + 1):
            seen_at.setdefault(count, time.monotonic())
        state = api.get(f"/dossiers/{domain}", token=token)
        assert state.status_code == 200, state.text
        dossier = state.json()
        if dossier["state"] in ("ready", "failed") and len(exact) >= 4:
            break
        time.sleep(0.05)
    assert dossier and dossier["state"] == "ready", dossier
    assert [call.get("status") for call in exact] == [429, 429, 429, 200], exact
    assert all(call.get("cost", 0) == 0 for call in exact[:3])
    assert exact[3].get("cost", 0) > 0
    assert all(seen_at[index + 1] - seen_at[index] >= 0.9 for index in (1, 2, 3)), seen_at


def test_all_provider_calls_failed_is_failed_and_refusals_are_free(
        mock_admin: MockAdmin, api: API, token: str) -> None:
    """F73-F74: complete provider outage fails quickly without mutating the prior dossier."""
    if not mock_admin.enabled:
        pytest.skip("provider fault injection requires DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    previous, _ = create(api, token, "all-fail-s4.test")
    previous_spend = previous["spent_units"]
    before_history = history(api, token, "all-fail-s4.test")
    before_feed = feed(api, token)
    mock_admin.reset()
    mock_admin.fault("nimble", ["search", "extract", "research"], "error")
    started = time.monotonic()
    response = api.post("/dossiers/all-fail-s4.test/refresh", token=token,
                        headers={"Idempotency-Key": key()})
    assert response.status_code == 202, response.text
    after = wait_dossier(api, token, "all-fail-s4.test", timeout=15)
    elapsed = time.monotonic() - started
    assert after["state"] == "failed", after
    assert elapsed < 10, elapsed
    assert after["fields"] == previous["fields"]
    assert after["spent_units"] == previous_spend
    assert history(api, token, "all-fail-s4.test") == before_history
    assert feed(api, token) == before_feed
    calls = mock_admin.calls()
    assert calls and all(call.get("status", 200) >= 400 for call in calls)
    assert all(call.get("cost", 0) == 0 for call in calls)
    exact_searches = [call for call in calls if call.get("method") == "search"
                      and call.get("query") == "all-fail-s4.test"]
    assert len(exact_searches) <= 3, exact_searches
