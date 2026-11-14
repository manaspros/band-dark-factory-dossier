"""Stage 3 times, executive candidates, and selection invariants (T3-T22)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from conftest import (API, FIELDS, FIELDS7, TEST_DOMAIN, TITLE_ORDER, assert_history_entry,
                      create_build, feed, history, new_key, parse_instant, refresh_build,
                      set_clock, stage2_rank_key)


def test_fields_candidates_and_executives_follow_the_public_shape(api: API, token: str) -> None:
    dossier, _ = create_build(api, token)
    assert dossier["state"] == "ready", dossier
    assert dossier["researched_at"] is not None
    assert list(dossier["fields"]) == list(FIELDS7)
    researched_at = parse_instant(dossier["researched_at"])

    for name in FIELDS:
        field = dossier["fields"][name]
        assert {"value", "status", "citations", "candidates", "true_from", "learned_at"} <= field.keys()
        candidates = field["candidates"]
        if not candidates:
            assert field["value"] is None and field["status"] == "unknown"
            assert field["citations"] == []
            assert field["true_from"] is None and field["learned_at"] is None
            continue

        assert len(candidates) == sum(c["selected"] is True for c in candidates) + \
            sum(c["selected"] is False for c in candidates)
        assert candidates[0]["selected"] is True
        assert sum(c["selected"] is True for c in candidates) == 1
        assert field["value"] == candidates[0]["value"]
        distinct = {(type(c["value"]), c["value"].strip() if isinstance(c["value"], str)
                     else c["value"]) for c in candidates}
        assert field["status"] == ("known" if len(distinct) == 1 else "contested")
        assert candidates == sorted(candidates, key=stage2_rank_key)
        assert field["citations"] == [
            {key: c[key] for key in ("url", "excerpt", "provider")}
            for c in candidates if c["value"] == field["value"]]
        for candidate in candidates:
            assert {"value", "url", "excerpt", "provider", "kind", "published_at",
                    "retrieved_at", "true_from", "learned_at", "selected"} <= candidate.keys()
            assert candidate["provider"] in ("nimble", "tavily", "kernel", "browserbase")
            assert candidate["kind"] in ("own", "filing", "news", "aggregator")
            assert 1 <= len(candidate["excerpt"]) <= 500
            assert parse_instant(candidate["retrieved_at"]) == researched_at
            assert parse_instant(candidate["learned_at"]) <= researched_at
            if candidate["true_from"] is not None:
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate["true_from"])
                datetime.strptime(candidate["true_from"], "%Y-%m-%d")
        selected = candidates[0]
        assert field["true_from"] == selected["true_from"]
        assert parse_instant(field["learned_at"]) == researched_at

    executives = dossier["fields"]["executives"]
    assert {"value", "status", "citations", "candidates", "true_from", "learned_at"} <= executives.keys()
    candidates = executives["candidates"]
    assert all("title" in c for c in candidates)
    assert [TITLE_ORDER[c["title"]] for c in candidates] == sorted(
        TITLE_ORDER[c["title"]] for c in candidates)
    members = []
    expected_citations = []
    contested = False
    for title in ("cfo", "coo", "cto"):
        group = [c for c in candidates if c["title"] == title]
        if not group:
            continue
        assert group == sorted(group, key=stage2_rank_key)
        assert sum(c["selected"] is True for c in group) == 1
        selected = next(c for c in group if c["selected"])
        members.append({"title": title, "name": selected["value"]})
        expected_citations.extend({key: c[key] for key in ("url", "excerpt", "provider")}
                                   for c in group if c["value"] == selected["value"])
        contested |= len({c["value"] for c in group}) > 1
    if not members:
        assert executives["value"] is None and executives["status"] == "unknown"
        assert executives["citations"] == [] and executives["true_from"] is None
        assert executives["learned_at"] is None
    else:
        assert executives["value"] == members
        assert executives["status"] == ("contested" if contested else "known")
        assert executives["citations"] == expected_citations
        selected_by_title = [next(c for c in candidates if c["title"] == member["title"]
                                  and c["selected"]) for member in members]
        dates = [c["true_from"] for c in selected_by_title]
        expected_true_from = None if any(date is None for date in dates) else max(dates)
        assert executives["true_from"] == expected_true_from


def test_candidate_true_from_matches_rendered_page_headers_when_mock_log_is_available(
        api: API, token: str, mock_admin) -> None:
    """T3-T4/T7/T14: effective date wins; otherwise use UTC published date or null."""
    if not mock_admin.enabled:
        import pytest
        pytest.skip("set DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN to inspect served page text")
    dossier, _ = create_build(api, token)
    pages = {}
    for call in mock_admin.calls():
        # Search results can include snippets in `served`; only extract records carry
        # the full rendered page text whose headers determine true_from.
        if call.get("method") != "extract":
            continue
        for page in call.get("served", []):
            pages[(call["provider"], page["url"])] = page.get("text", "")

    def header_value(text: str, key: str) -> str | None:
        lines = text.splitlines()
        for line in lines:
            if not line:
                break
            if line.startswith(key + ":"):
                return line.split(":", 1)[1].strip()
        return None

    checked = 0
    for field in dossier["fields"].values():
        for candidate in field["candidates"]:
            text = pages.get((candidate["provider"], candidate["url"]))
            if text is None:
                continue
            effective = header_value(text, "Effective")
            if effective and re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective):
                datetime.strptime(effective, "%Y-%m-%d")
                expected = effective
            else:
                published = header_value(text, "Published")
                if published:
                    try:
                        expected = parse_instant(published).astimezone(timezone.utc).date().isoformat()
                    except ValueError:
                        expected = None
                else:
                    expected = None
            assert candidate["true_from"] == expected, candidate
            assert " ".join(candidate["excerpt"].split()) in " ".join(text.split())
            checked += 1
    assert checked > 0, "mock log did not expose any candidate source text"


def test_candidate_learned_at_is_first_gather_and_retrieved_at_is_current_build_time(
        api: API, token: str) -> None:
    first, _ = create_build(api, token)
    first_candidates = {}
    for field_name, field in first["fields"].items():
        for candidate in field["candidates"]:
            key = (field_name, candidate.get("title"), candidate["value"], candidate["url"],
                   candidate["provider"])
            first_candidates[key] = candidate["learned_at"]

    set_clock(api, "2026-03-01T09:01:00+00:00")
    second, _ = refresh_build(api, token)
    assert second["researched_at"] == "2026-03-01T09:01:00+00:00"
    seen = 0
    for field_name, field in second["fields"].items():
        for candidate in field["candidates"]:
            assert candidate["retrieved_at"] == second["researched_at"]
            key = (field_name, candidate.get("title"), candidate["value"], candidate["url"],
                   candidate["provider"])
            if key in first_candidates:
                assert candidate["learned_at"] == first_candidates[key]
                seen += 1
            else:
                assert candidate["learned_at"] == second["researched_at"]
    assert seen > 0, "the configured corpus should return at least one candidate on both builds"


def test_fields_and_candidates_have_no_future_timestamps(api: API, token: str) -> None:
    dossier, _ = create_build(api, token)
    built_at = parse_instant(dossier["researched_at"])
    for field in dossier["fields"].values():
        if field["learned_at"] is not None:
            assert parse_instant(field["learned_at"]) <= built_at
        for candidate in field["candidates"]:
            assert parse_instant(candidate["learned_at"]) <= built_at


def test_initial_history_records_values_without_initial_feed_entries(api: API, token: str) -> None:
    dossier, _ = create_build(api, token)
    result = history(api, token, TEST_DOMAIN)
    assert result["domain"] == TEST_DOMAIN
    assert list(result["fields"]) == list(FIELDS7)
    assert feed(api, token)["changes"] == []
    for name in FIELDS7:
        value = dossier["fields"][name]["value"]
        entries = result["fields"][name]
        if value is None:
            assert entries == []
        else:
            assert len(entries) == 1
            assert entries[0]["type"] == "initial"
            assert entries[0]["value"] == value
            assert entries[0]["learned_at"] == dossier["researched_at"]
            assert entries[0]["true_from"] == dossier["fields"][name]["true_from"]
            assert_history_entry(entries[0])
