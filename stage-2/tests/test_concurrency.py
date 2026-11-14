"""Concurrent requests behave as if run one at a time (§7, §8, §11)."""
import asyncio

import httpx

from app.main import Services, create_app
from tests.fakes import DOMAIN, FakeWeb

FIXTURE = {"now": "2026-03-01T09:00:00+00:00",
           "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
                      "display_name": "Ada"}]}


async def _client_and_services():
    services = Services()
    web = FakeWeb(delay=0.05)
    app = create_app(services, web_factory=lambda: web)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    await client.post("/_test/reset", json=FIXTURE)
    token = (await client.post("/auth/login", json={"email": "ada@example.com",
                                                     "password": "correct horse"})).json()["token"]
    return client, services, web, {"Authorization": f"Bearer {token}"}


def test_concurrent_identical_requests_take_effect_once():
    async def scenario():
        client, services, web, h = await _client_and_services()
        responses = await asyncio.gather(*(client.post(
            "/dossiers", json={"domain": DOMAIN}, headers={**h, "Idempotency-Key": "same"})
            for _ in range(20)))
        await client.aclose()
        return responses, services

    responses, services = asyncio.run(scenario())
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200] * 19 + [202]
    assert len({r.text for r in responses}) == 1
    assert services.builds.started_count == 1


def test_concurrent_requests_with_distinct_keys_make_one_dossier():
    async def scenario():
        client, services, web, h = await _client_and_services()
        responses = await asyncio.gather(*(client.post(
            "/dossiers", json={"domain": DOMAIN}, headers={**h, "Idempotency-Key": f"k{i}"})
            for i in range(20)))
        refreshes = await asyncio.gather(*(client.post(
            f"/dossiers/{DOMAIN}/refresh", headers={**h, "Idempotency-Key": f"r{i}"})
            for i in range(5)))
        await client.aclose()
        return responses, refreshes, services

    responses, refreshes, services = asyncio.run(scenario())
    assert sorted(r.status_code for r in responses) == [200] * 19 + [202]
    assert len({r.json()["dossier_id"] for r in responses}) == 1
    assert all(r.status_code == 202 for r in refreshes)   # a build is running: no second one
    assert services.builds.started_count == 1
