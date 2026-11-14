"""No duplicate successful calls and investor UI visibility (F54, F86)."""
from __future__ import annotations

import os

import pytest

from conftest import API, DOMAIN, MockAdmin, create


def test_successful_identical_provider_requests_are_not_repeated(
        api: API, token: str, mock_admin: MockAdmin) -> None:
    """F86: per-build memos avoid duplicate successful search/extract calls."""
    if not mock_admin.enabled:
        pytest.skip("provider call memo assertion requires DOSSIER_MOCK_URL and DOSSIER_MOCK_TOKEN")
    mock_admin.reset()
    create(api, token, "memo-s4.test")
    successful = [call for call in mock_admin.calls() if call.get("status", 500) < 400]
    seen = set()
    for call in successful:
        method = call.get("method")
        if method not in ("search", "extract"):
            continue
        args = tuple((name, repr(call.get(name))) for name in
                     ("query", "url", "operation", "render", "provider_options")
                     if name in call)
        identity = call.get("provider"), method, args
        assert identity not in seen, call
        seen.add(identity)


def test_investors_section_is_visible_on_dossier_and_evidence_screens(api: API, token: str) -> None:
    """F54: optional browser check for the new visible field and absent legacy testids."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("install Playwright and Chromium to run browser screen checks")
    create(api, token)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 375, "height": 812})
        base = os.environ.get("DOSSIER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
        page.goto(base + "/login")
        page.get_by_test_id("login-email").fill("ada.s4@example.test")
        page.get_by_test_id("login-password").fill("correct horse battery")
        page.get_by_test_id("login-submit").click()
        page.wait_for_timeout(300)
        page.goto(f"{base}/dossiers/{DOMAIN}")
        page.get_by_text("Investors", exact=True).first.wait_for(timeout=10_000)
        assert page.locator('[data-testid="field-investors"]').count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        page.goto(f"{base}/dossiers/{DOMAIN}/evidence")
        page.get_by_text("Investors", exact=True).first.wait_for(timeout=10_000)
        assert page.locator('[data-testid^="candidate-investors-"]').count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        browser.close()
