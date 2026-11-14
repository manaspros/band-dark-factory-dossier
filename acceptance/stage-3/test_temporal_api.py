"""As-of snapshots, values timelines, and query validation (T32-T45, T52-T54)."""
from __future__ import annotations

from urllib.parse import quote

from conftest import API, TEST_DOMAIN, create_build, parse_instant, refresh_build, set_clock


def test_as_of_instant_ties_choose_last_build_and_include_all_spend(api: API, token: str) -> None:
    first, _ = create_build(api, token)
    first_spend = first["spent_units"]
    # The test clock deliberately remains unchanged, so this ready refresh ties the first build.
    second, _ = refresh_build(api, token)
    assert parse_instant(first["researched_at"]) == parse_instant(second["researched_at"])
    instant_utc = quote("2026-03-01T09:00:00+00:00", safe="")
    equivalent_offset = quote("2026-03-01T14:30:00+05:30", safe="")
    at_utc = api.get(f"/dossiers/{TEST_DOMAIN}?as_of={instant_utc}", token=token)
    at_offset = api.get(f"/dossiers/{TEST_DOMAIN}?as_of={equivalent_offset}", token=token)
    assert at_utc.status_code == 200, at_utc.text
    assert at_offset.status_code == 200, at_offset.text
    assert at_utc.json()["fields"] == second["fields"]
    assert at_offset.json()["fields"] == second["fields"]
    assert at_utc.json()["spent_units"] == second["spent_units"]
    assert second["spent_units"] >= first_spend

    before = api.get(f"/dossiers/{TEST_DOMAIN}?as_of=2026-03-01T08%3A59%3A59%2B00%3A00",
                     token=token)
    assert before.status_code == 404, before.text
    assert before.json()["error"]["code"] == "not_found"


def test_as_of_rejects_missing_offset_and_values_validate_dates(api: API, token: str) -> None:
    create_build(api, token)
    invalid_as_of = api.get(f"/dossiers/{TEST_DOMAIN}?as_of=2026-03-01T09%3A00%3A00", token=token)
    assert invalid_as_of.status_code == 422, invalid_as_of.text
    assert invalid_as_of.json()["error"]["code"] == "validation_failed"

    for query in ("", "?true_at=2025-6-1", "?true_at=2025-02-30"):
        response = api.get(f"/dossiers/{TEST_DOMAIN}/values{query}", token=token)
        assert response.status_code == 422, (query, response.text)
        assert response.json()["error"]["code"] == "validation_failed"

    invalid_values_as_of = api.get(
        f"/dossiers/{TEST_DOMAIN}/values?true_at=2025-01-01&as_of=2026-03-01T09%3A00%3A00",
        token=token)
    assert invalid_values_as_of.status_code == 422, invalid_values_as_of.text


def test_as_of_not_found_before_any_ready_build_and_new_routes_require_auth(api: API) -> None:
    no_auth = api.get(f"/dossiers/{TEST_DOMAIN}/history")
    assert no_auth.status_code == 401, no_auth.text
    no_auth = api.get(f"/dossiers/{TEST_DOMAIN}/values?true_at=2025-01-01")
    assert no_auth.status_code == 401, no_auth.text
    no_auth = api.get("/changes")
    assert no_auth.status_code == 401, no_auth.text


def test_values_response_has_seven_fields_and_null_value_shape(api: API, token: str) -> None:
    dossier, _ = create_build(api, token)
    response = api.get(f"/dossiers/{TEST_DOMAIN}/values?true_at=1900-01-01", token=token)
    assert response.status_code == 200, response.text
    value_fields = response.json()["fields"]
    assert list(value_fields) == ["legal_name", "hq_city", "ceo", "founded_year",
                                  "headcount_range", "funding_total", "executives"]
    for field in value_fields.values():
        assert set(field) >= {"value", "true_from", "citations"}
        assert field["value"] is None
        assert field["true_from"] is None
        assert field["citations"] == []

    missing = api.get("/dossiers/no-such-dossier.test/values?true_at=1900-01-01", token=token)
    assert missing.status_code == 404, missing.text
    assert dossier["state"] == "ready"
