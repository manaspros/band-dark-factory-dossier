"""Optional real-browser checks for required routes, test IDs and responsive behavior."""
from __future__ import annotations

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="install Playwright for browser checks")
from playwright.sync_api import sync_playwright

from conftest import API, ALICE, FIELDS, TEST_DOMAIN


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            instance = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Playwright Chromium is unavailable: {exc}")
        yield instance
        instance.close()


def sign_in(page, api: API) -> None:
    page.goto(api.base_url + "/login")
    page.get_by_test_id("login-email").fill(ALICE["email"])
    page.get_by_test_id("login-password").fill(ALICE["password"])
    page.get_by_test_id("login-submit").click()
    page.wait_for_timeout(250)
    assert page.get_by_test_id("current-user").inner_text().find(ALICE["display_name"]) >= 0


def test_required_routes_and_data_testids_at_mobile_and_desktop(browser, api: API, built: dict):
    """S46-S55, S63-S107: required controls/data are reachable and layouts do not overflow."""
    assert built["state"] == "ready", built
    page = browser.new_page(viewport={"width": 375, "height": 812})
    sign_in(page, api)

    page.goto(api.base_url + "/")
    for testid in ("research-domain", "research-submit", "dossier-search", "dossier-list",
                   f"dossier-item-{TEST_DOMAIN}", "current-user", "logout-button"):
        assert page.get_by_test_id(testid).count() > 0, testid
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    page.goto(api.base_url + f"/dossiers/{TEST_DOMAIN}")
    for testid in ("dossier-domain", "dossier-state", "dossier-spent", "dossier-evidence-link",
                   "dossier-refresh", "dossier-reload"):
        assert page.get_by_test_id(testid).count() == 1, testid
    for name in FIELDS:
        assert page.get_by_test_id(f"field-{name}").count() == 1
        assert page.get_by_test_id(f"field-citations-{name}").count() == 1
        field = built["fields"][name]
        if field["value"] is not None:
            assert page.get_by_test_id(f"field-value-{name}").count() == 1
        if field["status"] == "contested":
            assert page.get_by_test_id(f"field-contested-{name}").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    page.goto(api.base_url + f"/dossiers/{TEST_DOMAIN}/evidence")
    for name in FIELDS:
        assert page.get_by_test_id(f"evidence-{name}").count() == 1
        expected = len(built["fields"][name]["candidates"])
        if expected:
            assert page.get_by_test_id(f"candidate-{name}-1").count() == 1
        else:
            assert page.get_by_test_id(f"evidence-empty-{name}").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    page.goto(api.base_url + "/contested")
    assert page.get_by_test_id("contested-list").count() == 1
    if not any(field["status"] == "contested" for field in built["fields"].values()):
        assert page.get_by_test_id("empty-contested").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    page.set_viewport_size({"width": 1440, "height": 900})
    for width in (375, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        for route in ("/", "/signup", "/login", f"/dossiers/{TEST_DOMAIN}",
                      f"/dossiers/{TEST_DOMAIN}/evidence", "/contested"):
            page.goto(api.base_url + route)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), \
                (width, route)
    page.close()


def test_auth_pages_expose_labels_and_keyboard_focus(browser, api: API):
    """S61-S62: auth controls have labels and visible keyboard focus."""
    page = browser.new_page(viewport={"width": 375, "height": 812})
    page.goto(api.base_url + "/signup")
    for testid in ("signup-email", "signup-password", "signup-display-name", "signup-submit"):
        assert page.get_by_test_id(testid).count() == 1
    email = page.get_by_test_id("signup-email")
    assert email.evaluate("el => Array.from(el.labels || []).some(label => "
                          "!!(label.offsetWidth || label.offsetHeight || label.getClientRects().length))")
    page.keyboard.press("Tab")
    focused = page.locator(":focus")
    assert focused.count() == 1
    assert focused.evaluate("el => el.matches(':focus-visible')"), \
        "keyboard focus should be visibly indicated on the focused control"
    page.goto(api.base_url + "/login")
    for testid in ("login-email", "login-password", "login-submit"):
        assert page.get_by_test_id(testid).count() == 1
    page.close()


def test_empty_list_not_found_and_empty_contested(browser, api: API):
    """S74, S90, S98: required empty and missing-resource states are shown."""
    page = browser.new_page()
    sign_in(page, api)
    page.goto(api.base_url + "/")
    assert page.get_by_test_id("empty-dossiers").count() == 1
    page.goto(api.base_url + "/dossiers/missing-company.test")
    assert page.get_by_test_id("dossier-not-found").count() == 1
    page.goto(api.base_url + "/contested")
    assert page.get_by_test_id("empty-contested").count() == 1
    page.close()


def test_dossier_reload_latest_read_wins(browser, api: API, token: str):
    """S101: a delayed earlier read must not overwrite a later dossier read."""
    from conftest import begin_dossier, wait_dossier
    start = begin_dossier(api, token, "read-order.test")
    assert start.status_code == 202, start.text
    ready = wait_dossier(api, token, "read-order.test")
    page = browser.new_page()
    sign_in(page, api)
    page.goto(api.base_url + "/dossiers/read-order.test")
    held = []

    def reorder_reads(route):
        if not held:
            held.append(route)
            return
        route.fulfill(json={**ready, "state": "ready"})
        held.pop().fulfill(json={**ready, "state": "building"})

    page.route("**/dossiers/read-order.test", reorder_reads)
    page.get_by_test_id("dossier-reload").click()
    page.get_by_test_id("dossier-reload").click()
    page.wait_for_timeout(250)
    assert page.get_by_test_id("dossier-state").inner_text() == "ready"
    page.unroute("**/dossiers/read-order.test", reorder_reads)
    page.close()


def test_research_lost_response_is_uncertain_and_retry_reuses_request(browser, api: API):
    """S79-S80/S103-S106: lost successful response is uncertain and retry keeps same key/body."""
    page = browser.new_page()
    sign_in(page, api)
    captured = []

    def lose_first_response(route):
        request = route.request
        captured.append((request.headers.get("idempotency-key"), request.post_data))
        if len(captured) == 1:
            route.fetch()
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/dossiers", lose_first_response)
    page.get_by_test_id("research-domain").fill("uncertain-retry.test")
    page.get_by_test_id("research-submit").click()
    page.wait_for_timeout(250)
    assert page.get_by_test_id("research-uncertain").count() == 1
    assert page.get_by_test_id("research-error").count() == 0
    page.get_by_test_id("research-submit").click()
    page.wait_for_url("**/dossiers/uncertain-retry.test", timeout=5000)
    assert len(captured) >= 2
    assert captured[0] == captured[1]
    page.close()


def test_invalid_research_shows_refusal_and_citation_excerpt_is_text(browser, api: API,
                                                                     built: dict, token: str):
    """S58/S69: errors are visible; page excerpts render as text, not executable markup."""
    page = browser.new_page()
    sign_in(page, api)
    page.goto(api.base_url + "/")
    page.get_by_test_id("research-domain").fill("https://invalid.test/path")
    page.get_by_test_id("research-submit").click()
    page.wait_for_timeout(200)
    assert page.get_by_test_id("research-error").count() == 1

    dossier = dict(built)
    dossier["fields"] = {name: dict(field) for name, field in built["fields"].items()}
    for field in dossier["fields"].values():
        field["citations"] = [dict(c) for c in field["citations"]]
        field["candidates"] = [dict(c) for c in field["candidates"]]
    named_field = next(((name, item) for name, item in dossier["fields"].items()
                        if item["citations"]), None)
    if named_field is None:
        pytest.skip("configured corpus has no citation to exercise safe excerpt rendering")
    field_name, field = named_field
    payload = '<img src=x onerror="window.__acceptanceXss=true">'
    field["citations"][0]["excerpt"] = payload
    def serve_api_json(route):
        if route.request.method == "GET" and route.request.resource_type in ("fetch", "xhr"):
            route.fulfill(json=dossier)
        else:
            route.continue_()

    page.route(f"**/dossiers/{TEST_DOMAIN}", serve_api_json)
    page.goto(api.base_url + f"/dossiers/{TEST_DOMAIN}")
    citation = page.get_by_test_id(f"citation-{field_name}-1")
    citation.wait_for()
    assert page.evaluate("window.__acceptanceXss !== true")
    assert payload in citation.inner_text()
    assert page.locator("img").count() == 0
    page.close()
