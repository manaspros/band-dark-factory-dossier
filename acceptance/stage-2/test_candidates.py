"""Stage 2 candidate metadata, ordering, status and provider provenance."""
from __future__ import annotations

from datetime import datetime

import pytest

from conftest import API, FIELDS, TEST_DOMAIN, assert_stage2_field, collapsed, new_key, wait_dossier


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, value
    return parsed


def test_candidates_are_complete_ranked_records_and_drive_status(api: API, token: str,
                                                                  built: dict) -> None:
    """S2, S24, S28-S45: candidates define selection/status/citations in rule order."""
    assert built["state"] == "ready", built
    assert list(built["fields"]) == list(FIELDS)
    assert built["researched_at"] is not None
    for name in FIELDS:
        field = built["fields"][name]
        assert_stage2_field(name, field, built["researched_at"])
        for candidate in field["candidates"]:
            assert parse_timestamp(candidate["retrieved_at"]) == \
                parse_timestamp(built["researched_at"])
            if candidate["published_at"] is not None:
                parse_timestamp(candidate["published_at"])
            assert candidate["kind"] in ("own", "filing", "news", "aggregator")
            assert candidate["provider"] in ("nimble", "tavily", "kernel", "browserbase")
    assert any(len(field["candidates"]) > 1 for field in built["fields"].values()), \
        "configured test corpus must include at least one field with competing candidates"

    page = api.get("/dossiers", token=token)
    assert page.status_code == 200, page.text
    entry = next(item for item in page.json()["dossiers"] if item["domain"] == TEST_DOMAIN)
    assert entry["legal_name"] == built["fields"]["legal_name"]["value"]


def test_candidate_citations_are_pages_actually_served_when_mock_log_is_available(
        built: dict, mock_admin) -> None:
    """S7/S9/S10/S27/S29: each excerpt and provider originate in served rendered text."""
    if not mock_admin.enabled:
        pytest.skip("set DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN to inspect served-page provenance")
    calls = mock_admin.calls()
    served = [(call["provider"], page["url"], collapsed(page["text"]))
              for call in calls for page in call.get("served", [])]
    for field in built["fields"].values():
        for candidate in field["candidates"]:
            excerpt = collapsed(candidate["excerpt"])
            assert any(provider == candidate["provider"] and url == candidate["url"]
                       and excerpt in text for provider, url, text in served), candidate


def test_rendered_provider_spend_is_at_most_80_and_domain_search_is_unique(
        api: API, token: str, mock_admin) -> None:
    """R1/R2/R62/R152/R213; S11/S15/S25/S117: provider evidence, query and budget limits."""
    if not mock_admin.enabled:
        pytest.skip("provider accounting needs DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.reset()
    response = api.post("/dossiers", token=token, headers={"Idempotency-Key": "budget-check"},
                        json={"domain": TEST_DOMAIN})
    assert response.status_code == 202, response.text
    dossier = wait_dossier(api, token, TEST_DOMAIN, timeout=300)
    calls = mock_admin.calls()
    charged = sum(call["cost"] for call in calls)
    assert charged <= 80, calls
    assert dossier["spent_units"] == charged
    successful_domain_searches = [call for call in calls
                                  if call["method"] == "search"
                                  and call.get("query") == TEST_DOMAIN
                                  and call["status"] < 400]
    assert len(successful_domain_searches) == 1, successful_domain_searches
    rendered = [call for call in calls if call["method"] == "extract"
                and call["provider"] == "nimble"]
    assert all(call["cost"] in (0, 3) for call in rendered), rendered


def test_429_retries_wait_and_eventually_succeed(api: API, token: str, mock_admin) -> None:
    """S20-S23/R155/R127: 429 is free, retried after the rate-limit interval, and bounded."""
    if not mock_admin.enabled:
        pytest.skip("429 behavior needs DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.reset()
    mock_admin.fault("nimble", ["search"], "rate_limit")
    response = api.post("/dossiers", token=token, headers={"Idempotency-Key": "retry-429-check"},
                        json={"domain": TEST_DOMAIN})
    assert response.status_code == 202, response.text

    # Poll the call log so response times can be compared without any server internals.
    observed: list[tuple[float, list[dict]]] = []
    import time
    deadline = time.monotonic() + 300
    last_count = -1
    while time.monotonic() < deadline:
        calls = mock_admin.calls()
        domain_calls = [call for call in calls if call["method"] == "search"
                        and call.get("query") == TEST_DOMAIN and call["provider"] == "nimble"]
        if len(domain_calls) != last_count:
            observed.append((time.monotonic(), domain_calls))
            last_count = len(domain_calls)
        if domain_calls and domain_calls[-1]["status"] < 400:
            break
        state = api.get(f"/dossiers/{TEST_DOMAIN}", token=token).json()["state"]
        if state in ("ready", "failed") and domain_calls:
            break
        time.sleep(0.025)

    domain_calls = [call for call in mock_admin.calls() if call["method"] == "search"
                    and call.get("query") == TEST_DOMAIN and call["provider"] == "nimble"]
    assert [call["status"] for call in domain_calls] == [429, 429, 429, 200], domain_calls
    response_times = [(stamp, len(calls)) for stamp, calls in observed if calls]
    first_seen: dict[int, float] = {}
    for stamp, count in response_times:
        first_seen.setdefault(count, stamp)
    for attempt in range(1, 4):
        assert first_seen[attempt + 1] - first_seen[attempt] >= 0.9, first_seen
    assert all(call["cost"] == 0 for call in domain_calls[:3])
    assert domain_calls[3]["cost"] > 0


def test_provider_refusals_are_contained_and_failed_build_is_not_a_5xx(api: API, token: str,
                                                                        mock_admin) -> None:
    """Stage 1 R91, R124, R155; S20: provider HTTP errors stay inside the build."""
    if not mock_admin.enabled:
        pytest.skip("provider refusal behavior needs DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.fault("nimble", ["search", "extract", "research"], "error")
    response = api.post("/dossiers", token=token, headers={"Idempotency-Key": new_key()},
                        json={"domain": "provider-error.test"})
    assert response.status_code == 202, response.text
    failed = wait_dossier(api, token, "provider-error.test", timeout=60)
    assert failed["state"] == "failed", failed
    for field in failed["fields"].values():
        assert field["value"] is None and field["status"] == "unknown"
        assert field["citations"] == [] and field["candidates"] == []
    domain_searches = [call for call in mock_admin.calls()
                       if call["provider"] == "nimble" and call["method"] == "search"
                       and call["query"] == "provider-error.test"]
    assert 1 <= len(domain_searches) <= 3, domain_searches
    assert all(call["status"] >= 400 and call["cost"] == 0
               for call in domain_searches), domain_searches
