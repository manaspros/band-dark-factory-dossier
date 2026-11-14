"""Uncertain writes, latest-read-wins and polling, with request interception."""
import asyncio, json, sys, time, urllib.request
from playwright.async_api import async_playwright, expect
BASE, WEB = sys.argv[1], sys.argv[2]
ADMIN = {"X-Mock-Admin": "local-admin", "content-type": "application/json"}
def mock(method, path, body=None):
    r = urllib.request.Request(WEB + path, data=json.dumps(body).encode() if body is not None else None,
                               method=method, headers=ADMIN)
    with urllib.request.urlopen(r) as resp:
        raw = resp.read(); return json.loads(raw) if raw else None
results = []
def check(name, ok, detail=""):
    results.append((name, ok)); print("PASS" if ok else "FAIL", name, detail)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(base_url=BASE)
        await page.goto("/signup")
        await page.get_by_test_id("signup-email").fill(f"b{time.time_ns()}@example.com")
        await page.get_by_test_id("signup-display-name").fill("Behaviour")
        await page.get_by_test_id("signup-password").fill("correct horse")
        await page.get_by_test_id("signup-submit").click()
        await expect(page.get_by_test_id("current-user")).to_be_visible()
        mock("POST", "/_mock/reset", {"epoch": 0})

        # 1. research response lost after the server committed
        keys = []
        async def lose(route, request):
            if request.method == "POST":
                keys.append(request.headers.get("idempotency-key"))
                await route.fetch()          # the server commits
                await route.abort()          # but the browser never hears back
            else:
                await route.continue_()
        await page.route("**/dossiers", lose)
        await page.get_by_test_id("research-domain").fill("quillmate.test")
        await page.get_by_test_id("research-submit").click()
        await expect(page.get_by_test_id("research-uncertain")).to_be_visible()
        check("research: uncertain shown, no error", await page.get_by_test_id("research-error").count() == 0)
        await page.unroute("**/dossiers")
        async def watch(route, request):
            if request.method == "POST": keys.append(request.headers.get("idempotency-key"))
            await route.continue_()
        await page.route("**/dossiers", watch)
        await page.get_by_test_id("research-uncertain").get_by_role("button").click()
        await page.wait_for_url("**/dossiers/quillmate.test")
        await expect(page.get_by_test_id("dossier-state")).to_have_text("ready", timeout=10000)
        check("research: retry reused the key", len(keys) == 2 and keys[0] == keys[1], keys)
        domain_searches = [c for c in mock("GET", "/_mock/log")["calls"]
                           if c["method"] == "search" and c["query"] == "quillmate.test"]
        check("research: one build", len(domain_searches) == 1, len(domain_searches))
        await page.unroute("**/dossiers")

        # 2. refresh response lost
        rkeys = []
        async def lose_refresh(route, request):
            rkeys.append(request.headers.get("idempotency-key"))
            await route.fetch(); await route.abort()
        await page.route("**/refresh", lose_refresh)
        await page.get_by_test_id("dossier-refresh").click()
        await expect(page.get_by_test_id("refresh-uncertain")).to_be_visible()
        check("refresh: uncertain, no error", await page.get_by_test_id("refresh-error").count() == 0)
        await page.unroute("**/refresh")
        async def watch_refresh(route, request):
            rkeys.append(request.headers.get("idempotency-key")); await route.continue_()
        await page.route("**/refresh", watch_refresh)
        await page.get_by_test_id("refresh-uncertain").get_by_role("button").click()
        await expect(page.get_by_test_id("refresh-uncertain")).to_have_count(0)
        check("refresh: retry reused the key", len(rkeys) == 2 and rkeys[0] == rkeys[1], rkeys)
        await expect(page.get_by_test_id("dossier-state")).to_have_text("ready", timeout=10000)
        await page.unroute("**/refresh")

        # 3. latest read wins: a slow earlier reload must not overwrite a later one
        await asyncio.sleep(2)
        real = await page.evaluate("""async () => { const s = JSON.parse(localStorage.getItem('dossier.session'));
            const r = await fetch('/dossiers/quillmate.test', {headers: {Authorization: 'Bearer ' + s.token}});
            return (await r.json()).spent_units; }""")
        calls = {"n": 0}
        async def slow_first(route, request):
            if request.method != "GET" or "evidence" in request.url:
                await route.continue_(); return
            calls["n"] += 1
            response = await route.fetch()
            body = await response.json()
            if calls["n"] == 1:
                body["spent_units"] = 1; body["state"] = "building"   # a stale answer
                await asyncio.sleep(2.5)
            await route.fulfill(response=response, json=body)
        await page.route("**/dossiers/quillmate.test", slow_first)
        await page.get_by_test_id("dossier-reload").click()
        await asyncio.sleep(0.3)
        await page.get_by_test_id("dossier-reload").click()
        await asyncio.sleep(3.5)
        shown = int(await page.get_by_test_id("dossier-spent").get_attribute("data-units"))
        state = await page.get_by_test_id("dossier-state").text_content()
        check("latest read wins", shown == real and state == "ready", (shown, real, state))
        await page.unroute("**/dossiers/quillmate.test")

        # 4. polling while building ends on ready without a click
        mock("POST", "/_mock/faults", {"provider": "nimble", "methods": ["search"], "mode": "delay", "seconds": 3})
        await page.get_by_test_id("dossier-refresh").click()
        await expect(page.get_by_test_id("dossier-state")).to_have_text("building", timeout=5000)
        await expect(page.get_by_test_id("dossier-state")).to_have_text("ready", timeout=15000)
        check("polling reaches ready", True)
        mock("POST", "/_mock/faults", {"provider": "nimble", "methods": ["search"], "mode": "none"})
        await browser.close()
asyncio.run(main())
print("SUMMARY", sum(ok for _, ok in results), "/", len(results))
