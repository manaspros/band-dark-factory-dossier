"""Walk every screen at 375 and 1280 px: testids, horizontal scroll, labels; screenshots."""
import sys
from playwright.sync_api import sync_playwright, expect
BASE = sys.argv[1]; OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/builder-ui"
problems = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (375, 1280):
        page = browser.new_page(viewport={"width": width, "height": 900}, base_url=BASE)
        page.on("pageerror", lambda e: problems.append(f"js error: {e}"))
        page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        page.goto("/signup")
        page.get_by_test_id("signup-email").fill(f"ui{width}-{__import__('time').time_ns()}@example.com")
        page.get_by_test_id("signup-display-name").fill(f"Ui {width}")
        page.get_by_test_id("signup-password").fill("correct horse")
        page.get_by_test_id("signup-submit").click()
        expect(page.get_by_test_id("current-user")).to_be_visible()
        page.get_by_test_id("research-domain").fill("not a domain")
        page.get_by_test_id("research-submit").click()
        expect(page.get_by_test_id("research-error")).to_be_visible()
        page.screenshot(path=f"{OUT}/list-error-{width}.png", full_page=True)
        page.get_by_test_id("research-domain").fill("WWW.Halvorsen-Robotics.TEST")
        page.get_by_test_id("research-submit").click()
        page.wait_for_url("**/dossiers/halvorsen-robotics.test")
        expect(page.get_by_test_id("dossier-state")).to_have_text("ready", timeout=10000)
        assert page.get_by_test_id("research-error").count() == 0
        page.screenshot(path=f"{OUT}/dossier-{width}.png", full_page=True)
        routes = ["/", "/dossiers/halvorsen-robotics.test", "/dossiers/halvorsen-robotics.test/evidence",
                  "/contested", "/dossiers/nobody-here.test", "/login", "/signup"]
        for route in routes:
            page.goto(route)
            page.wait_for_load_state("networkidle")
            sw = page.evaluate("document.documentElement.scrollWidth")
            if sw > width:
                problems.append(f"{route} @{width}: scrollWidth {sw}")
            unlabeled = page.evaluate("""[...document.querySelectorAll('input')].filter(i =>
                !(i.id && document.querySelector(`label[for="${i.id}"]`))).length""")
            if unlabeled:
                problems.append(f"{route} @{width}: {unlabeled} inputs without a label")
            name = route.strip("/").replace("/", "_") or "list"
            page.screenshot(path=f"{OUT}/{name}-{width}.png", full_page=True)
        page.goto("/dossiers/halvorsen-robotics.test")
        expect(page.get_by_test_id("dossier-state")).to_have_text("ready")
        ids = page.evaluate("[...document.querySelectorAll('[data-testid]')].map(e => e.dataset.testid)")
        for need in ["dossier-domain", "dossier-spent", "dossier-researched-at", "dossier-evidence-link",
                     "dossier-refresh", "dossier-reload"] + [f"field-{f}" for f in
                     ["legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total"]]:
            if need not in ids: problems.append(f"missing {need}")
        print(width, "testids on dossier:", len(ids), "contested markers:",
              sum(1 for i in ids if i.startswith("field-contested-")))
        page.get_by_test_id("dossier-refresh").click()
        expect(page.get_by_test_id("dossier-state")).to_have_text("ready", timeout=10000)
        page.goto("/contested")
        page.wait_for_load_state("networkidle")
        print(width, "contested items:", page.locator("[data-testid^=contested-item-]").count())
        page.get_by_test_id("logout-button").click()
        page.wait_for_url("**/login")
    browser.close()
print("PROBLEMS:", problems or "none")
