"""History typing, feed sequence, and failed/concurrent build behavior (T2, T23-T31, T46-T53, T66)."""
from __future__ import annotations

from conftest import (API, FIELDS7, TEST_DOMAIN, create_build, feed, history,
                      new_key, parse_instant, refresh_build, set_clock, wait_dossier)


def test_unchanged_selected_values_add_no_history_or_feed_entry(api: API, token: str) -> None:
    before, _ = create_build(api, token)
    before_history = history(api, token, TEST_DOMAIN)["fields"]
    before_feed = feed(api, token)["changes"]

    set_clock(api, "2026-03-01T09:01:00+00:00")
    after, _ = refresh_build(api, token)
    after_history = history(api, token, TEST_DOMAIN)["fields"]
    after_feed = feed(api, token)["changes"]

    assert list(after_history) == list(FIELDS7)
    for name in FIELDS7:
        if before["fields"][name]["value"] == after["fields"][name]["value"]:
            assert after_history[name] == before_history[name], name
    # This configured corpus is stable across refreshes; if a provider changes its answer,
    # the changed field must have one history/feed item instead of making this a false failure.
    changed = [name for name in FIELDS7
               if before["fields"][name]["value"] != after["fields"][name]["value"]]
    assert len(after_feed) - len(before_feed) == len(changed)
    for name in changed:
        assert len(after_history[name]) == len(before_history[name]) + 1
        assert after_history[name][-1]["type"] in ("change", "correction")
        assert sum(entry["field"] == name for entry in after_feed) == \
            sum(entry["field"] == name for entry in before_feed) + 1


def test_changed_selected_values_get_one_typed_history_and_feed_entry(api: API,
                                                                      token: str) -> None:
    """T23-T31, T49-T51: each changed ordinary field gets one entry of the specified type."""
    before, _ = create_build(api, token)
    previous_history = history(api, token, TEST_DOMAIN)["fields"]
    previous_feed = feed(api, token)["changes"]
    set_clock(api, "2026-03-02T09:00:00+00:00")
    after, _ = refresh_build(api, token)
    new_history = history(api, token, TEST_DOMAIN)["fields"]
    new_feed = feed(api, token)["changes"]
    changed = [name for name in FIELDS7[:6]
               if before["fields"][name]["value"] != after["fields"][name]["value"]]
    for name in changed:
        delta = new_history[name][len(previous_history[name]):]
        assert len(delta) == 1, (name, delta)
        entry = delta[0]
        old, new = before["fields"][name], after["fields"][name]
        expected = "correction" if (
            old["value"] is not None and new["value"] is not None
            and old["true_from"] is not None and new["true_from"] is not None
            and new["true_from"] <= old["true_from"]
        ) else "change"
        assert entry["type"] == expected
        assert entry["value"] == new["value"]
        matches = [item for item in new_feed[len(previous_feed):]
                   if item["field"] == name]
        assert len(matches) == 1
        assert matches[0]["type"] == expected
        assert matches[0]["from"] == old["value"] and matches[0]["to"] == new["value"]


def test_feed_sequence_is_unique_monotonic_and_since_limit_page(api: API, token: str) -> None:
    first, _ = create_build(api, token)
    set_clock(api, "2026-03-01T09:01:00+00:00")
    second, _ = refresh_build(api, token)
    full = feed(api, token, since=0, limit=200)
    entries = full["changes"]
    seqs = [entry["seq"] for entry in entries]
    assert seqs == sorted(set(seqs))
    assert all(isinstance(seq, int) and seq > 0 for seq in seqs)
    if entries:
        page = feed(api, token, since=entries[0]["seq"], limit=1)
        assert all(item["seq"] > entries[0]["seq"] for item in page["changes"])
        assert page["changes"] == entries[1:2]
        assert page["has_more"] is (len(entries) > 2)
    assert second["spent_units"] >= first["spent_units"]


def test_changes_query_defaults_and_validates_since_and_limit(api: API, token: str) -> None:
    """T52-T53: feed paging defaults and bounds are observable through the API."""
    default = api.get("/changes", token=token)
    explicit = api.get("/changes?since=0&limit=50", token=token)
    assert default.status_code == explicit.status_code == 200
    assert default.json() == explicit.json()
    for query in ("?since=-1", "?since=x", "?limit=0", "?limit=201", "?limit=x"):
        response = api.get("/changes" + query, token=token)
        assert response.status_code == 422, (query, response.text)


def test_simultaneous_executive_title_changes_are_one_aggregate_entry(api: API, token: str) -> None:
    """T23/E3-7: executives is one field entry even when multiple titles differ."""
    first, _ = create_build(api, token)
    first_exec = first["fields"]["executives"]["value"]
    if not first_exec or len(first_exec) < 2:
        import pytest
        pytest.skip("the configured corpus has fewer than two selected executive titles")
    # A refresh over the fixed mock corpus is a safe public operation; this assertion is
    # conditional on it producing more than one changed title in the suite's corpus.
    set_clock(api, "2026-03-01T09:01:00+00:00")
    second, _ = refresh_build(api, token)
    second_exec = second["fields"]["executives"]["value"]
    old = {member["title"]: member["name"] for member in first_exec}
    new = {member["title"]: member["name"] for member in second_exec or []}
    differing = [title for title in ("cfo", "coo", "cto") if old.get(title) != new.get(title)]
    if len(differing) < 2:
        import pytest
        pytest.skip("the fixed corpus did not change multiple executive titles in one refresh")
    entries = history(api, token, TEST_DOMAIN)["fields"]["executives"]
    matching = [entry for entry in entries if entry["value"] == second_exec]
    assert len(matching) == 1
    assert matching[0]["value"] == second_exec
    all_feed = feed(api, token)["changes"]
    exec_feed = [entry for entry in all_feed if entry["field"] == "executives"]
    assert exec_feed and exec_feed[-1]["to"] == second_exec
    assert exec_feed[-1]["field"] == "executives"

    def title_dates(dossier):
        return {candidate["title"]: candidate["true_from"]
                for candidate in dossier["fields"]["executives"]["candidates"]
                if candidate["selected"]}

    old_dates, new_dates = title_dates(first), title_dates(second)
    corrections = []
    for title in differing:
        old_date, new_date = old_dates.get(title), new_dates.get(title)
        corrections.append(title in old and title in new and old_date is not None
                           and new_date is not None and new_date <= old_date)
    expected_type = "correction" if all(corrections) else "change"
    assert matching[0]["type"] == expected_type
    assert exec_feed[-1]["type"] == expected_type


def test_failed_refresh_preserves_last_ready_fields_history_and_feed(api: API, token: str,
                                                                      mock_admin) -> None:
    if not mock_admin.enabled:
        import pytest
        pytest.skip("provider failure injection needs DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    ready, _ = create_build(api, token)
    before_history = history(api, token, TEST_DOMAIN)
    before_feed = feed(api, token)
    mock_admin.fault("nimble", ["search", "extract", "research"], "error")
    response = api.post(f"/dossiers/{TEST_DOMAIN}/refresh", token=token,
                        headers={"Idempotency-Key": new_key()})
    assert response.status_code == 202, response.text
    after = wait_dossier(api, token, TEST_DOMAIN)
    assert after["state"] == "failed", after
    assert after["fields"] == ready["fields"]
    assert history(api, token, TEST_DOMAIN) == before_history
    assert feed(api, token) == before_feed


def test_concurrent_refreshes_do_not_duplicate_feed_entries(api: API, token: str) -> None:
    import concurrent.futures

    create_build(api, token)
    before = feed(api, token)["changes"]
    before_dossier = api.get(f"/dossiers/{TEST_DOMAIN}", token=token).json()

    def send_refresh(i: int):
        return api.post(f"/dossiers/{TEST_DOMAIN}/refresh", token=token,
                        headers={"Idempotency-Key": f"concurrent-stage3-{i}"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send_refresh, range(8)))
    assert all(response.status_code == 202 for response in responses), \
        [response.text for response in responses]
    after_dossier = wait_dossier(api, token, TEST_DOMAIN)
    after = feed(api, token)["changes"]
    assert len(after) >= len(before)
    assert [item["seq"] for item in after] == sorted({item["seq"] for item in after})
    for field_name in FIELDS7:
        old = before_dossier["fields"][field_name]["value"]
        new = after_dossier["fields"][field_name]["value"]
        if old == new:
            assert sum(entry["field"] == field_name for entry in after) == \
                sum(entry["field"] == field_name for entry in before)
