"""HTTP-only helpers shared by the Stage 2 acceptance tests."""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
import requests


BASE_URL = os.environ.get("DOSSIER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
TEST_DOMAIN = os.environ.get("DOSSIER_TEST_DOMAIN", "halvorsen-robotics.test")
NOW = "2026-03-01T09:00:00+00:00"
ALICE = {"id": "accept_ada", "email": "ada.acceptance@example.test",
         "password": "correct horse battery", "display_name": "Ada Acceptance"}
BOB = {"id": "accept_bob", "email": "bob.acceptance@example.test",
       "password": "correct horse battery", "display_name": "Bob Acceptance"}
FIELDS = ("legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total")
PROVIDER_ORDER = {name: rank for rank, name in enumerate(("nimble", "tavily", "kernel", "browserbase"))}
KINDS = {"own": 0, "filing": 0, "news": 1, "aggregator": 2, None: 2}


@dataclass
class API:
    """Small requests wrapper; each request has the service's per-request timeout."""

    base_url: str = BASE_URL

    def request(self, method: str, path: str, *, token: str | None = None,
                timeout: float = 5, **kwargs: Any) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return requests.request(method, self.base_url + path, headers=headers,
                                timeout=timeout, **kwargs)

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def login(self, user: dict = ALICE) -> str:
        response = self.post("/auth/login", json={"email": user["email"],
                                                   "password": user["password"]})
        assert response.status_code == 200, response.text
        return response.json()["token"]


@pytest.fixture(scope="session")
def api() -> API:
    return API()


@pytest.fixture(autouse=True)
def reset_service(api: API) -> None:
    """Stage 1 §3.3/Stage 2 baseline: each test starts from only its seeded accounts."""
    response = api.post("/_test/reset", timeout=10,
                        json={"now": NOW, "users": [ALICE, BOB]})
    assert response.status_code == 204, response.text


@pytest.fixture
def users(api: API) -> dict[str, str]:
    return {"alice": api.login(ALICE), "bob": api.login(BOB)}


@pytest.fixture
def token(users: dict[str, str]) -> str:
    return users["alice"]


def new_key() -> str:
    return "acceptance-" + uuid.uuid4().hex


def wait_dossier(api: API, token: str, domain: str, *, timeout: float = 300) -> dict:
    """Poll only the documented dossier read until the build reaches a terminal state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = api.get(f"/dossiers/{domain}", token=token)
        assert response.status_code == 200, response.text
        dossier = response.json()
        if dossier["state"] in ("ready", "failed"):
            return dossier
        time.sleep(0.1)
    raise AssertionError(f"build for {domain} did not finish within {timeout:g}s")


def begin_dossier(api: API, token: str, domain: str = TEST_DOMAIN,
                  key: str | None = None) -> requests.Response:
    return api.post("/dossiers", token=token, json={"domain": domain},
                    headers={"Idempotency-Key": key or new_key()})


@pytest.fixture
def built(api: API, token: str) -> dict:
    """Create the configured sample dossier and wait for its completed build."""
    response = begin_dossier(api, token)
    assert response.status_code == 202, response.text
    return wait_dossier(api, token, TEST_DOMAIN)


def collapsed(value: str) -> str:
    return " ".join(value.split())


def candidate_sort_key(candidate: dict) -> tuple:
    """Stage 2 §The selection rule, expressed independently for response verification."""
    from datetime import datetime

    published = candidate["published_at"]
    instant = datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
    value = candidate["value"]
    value_key = (0, value) if isinstance(value, int) and not isinstance(value, bool) else (1, value.strip())
    return (KINDS[candidate["kind"]], instant is None,
            -(instant.timestamp()) if instant else 0,
            tuple(map(ord, candidate["url"])), PROVIDER_ORDER[candidate["provider"]], value_key)


def assert_stage2_field(name: str, field: dict, researched_at: str) -> None:
    """Stage 2 candidates/status/citations invariants for one field."""
    assert {"value", "status", "citations", "candidates"} <= set(field), (name, field)
    candidates = field["candidates"]
    if not candidates:
        assert field["value"] is None and field["status"] == "unknown"
        assert field["citations"] == []
        return

    required = {"value", "url", "excerpt", "provider", "kind", "published_at",
                "retrieved_at", "selected"}
    assert all(required <= set(candidate) for candidate in candidates), (name, candidates)
    assert candidates == sorted(candidates, key=candidate_sort_key), (name, candidates)
    assert sum(candidate["selected"] is True for candidate in candidates) == 1
    assert candidates[0]["selected"] is True
    assert all(candidate["selected"] is False for candidate in candidates[1:])
    assert field["value"] == candidates[0]["value"]
    distinct = {(type(candidate["value"]).__name__,
                 candidate["value"].strip() if isinstance(candidate["value"], str)
                 else candidate["value"]) for candidate in candidates}
    assert field["status"] == ("known" if len(distinct) == 1 else "contested")
    matching = [candidate for candidate in candidates if candidate["value"] == field["value"]]
    assert field["citations"] == [
        {key: candidate[key] for key in ("url", "excerpt", "provider")}
        for candidate in matching]
    for candidate in candidates:
        assert isinstance(candidate["excerpt"], str) and 1 <= len(candidate["excerpt"]) <= 500
        assert candidate["excerpt"] == candidate["excerpt"].strip()
        assert len(candidate["excerpt"]) <= 500
        assert candidate["provider"] in PROVIDER_ORDER
        assert candidate["kind"] in KINDS
        assert candidate["retrieved_at"] == researched_at


class MockAdmin:
    """Optional mock-web call log/fault API, enabled only when the harness exposes it."""

    def __init__(self) -> None:
        self.url = os.environ.get("DOSSIER_MOCK_URL", "").rstrip("/")
        self.token = os.environ.get("DOSSIER_MOCK_TOKEN", "")
        self.enabled = bool(self.url and self.token)

    def request(self, method: str, path: str, *, json_body: dict | None = None) -> dict | None:
        if not self.enabled:
            return None
        response = requests.request(method, self.url + path,
                                    headers={"X-Mock-Admin": self.token},
                                    json=json_body, timeout=10)
        assert response.status_code in (200, 204), response.text
        return response.json() if response.content else None

    def reset(self) -> None:
        self.request("POST", "/_mock/reset", json_body={"epoch": 0})

    def fault(self, provider: str, methods: list[str], mode: str) -> None:
        self.request("POST", "/_mock/faults", json_body={"provider": provider,
                                                              "methods": methods,
                                                              "mode": mode})

    def calls(self) -> list[dict]:
        answer = self.request("GET", "/_mock/log")
        return answer["calls"] if answer else []


@pytest.fixture
def mock_admin() -> MockAdmin:
    return MockAdmin()


@pytest.fixture(autouse=True)
def reset_mock_log_between_tests() -> None:
    """Keep optional provider-log assertions scoped to calls from their own test."""
    mock = MockAdmin()
    if mock.enabled:
        mock.reset()
