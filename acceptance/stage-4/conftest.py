"""Black-box HTTP helpers for Stage 4 acceptance checks."""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
import requests

BASE_URL = os.environ.get("DOSSIER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
DOMAIN = os.environ.get("DOSSIER_TEST_DOMAIN", "halvorsen-robotics.test")
NOW = "2026-03-01T09:00:00+00:00"
ALICE = {"id": "s4_accept_ada", "email": "ada.s4@example.test", "password": "correct horse battery", "display_name": "Ada Stage Four"}
BOB = {"id": "s4_accept_bob", "email": "bob.s4@example.test", "password": "correct horse battery", "display_name": "Bob Stage Four"}
FIELDS6 = ("legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total")
FIELDS8 = FIELDS6 + ("executives", "investors")


@dataclass
class API:
    base_url: str = BASE_URL

    def request(self, method: str, path: str, *, token: str | None = None, timeout: float = 10, **kwargs: Any) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return requests.request(method, self.base_url + path, headers=headers, timeout=timeout, **kwargs)

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def login(self, user: dict = ALICE) -> str:
        response = self.post("/auth/login", json={"email": user["email"], "password": user["password"]})
        assert response.status_code == 200, response.text
        return response.json()["token"]


class MockAdmin:
    """Optional published mock control/log interface."""
    def __init__(self) -> None:
        self.url = os.environ.get("DOSSIER_MOCK_URL", "").rstrip("/")
        self.token = os.environ.get("DOSSIER_MOCK_TOKEN", "")
        self.enabled = bool(self.url and self.token)

    def request(self, method: str, path: str, body: dict | None = None) -> dict | None:
        if not self.enabled:
            return None
        response = requests.request(method, self.url + path, headers={"X-Mock-Admin": self.token}, json=body, timeout=10)
        assert response.status_code in (200, 204), response.text
        return response.json() if response.content else None

    def reset(self) -> None:
        self.request("POST", "/_mock/reset", {"epoch": 0})

    def fault(self, provider: str, methods: list[str], mode: str) -> None:
        self.request("POST", "/_mock/faults", {"provider": provider, "methods": methods, "mode": mode})

    def delay(self, provider: str, methods: list[str], seconds: float) -> None:
        self.request("POST", "/_mock/faults", {"provider": provider, "methods": methods,
                                                 "mode": "delay", "seconds": seconds})

    def calls(self) -> list[dict]:
        result = self.request("GET", "/_mock/log")
        return result["calls"] if result else []


@pytest.fixture(scope="session")
def api() -> API:
    return API()


@pytest.fixture(autouse=True)
def reset_state(api: API) -> None:
    response = api.post("/_test/reset", json={"now": NOW, "users": [ALICE, BOB]}, timeout=20)
    assert response.status_code == 204, response.text
    mock = MockAdmin()
    if mock.enabled:
        mock.reset()


@pytest.fixture
def token(api: API) -> str:
    return api.login()


@pytest.fixture
def mock_admin() -> MockAdmin:
    return MockAdmin()


def key() -> str:
    return "stage4-accept-" + uuid.uuid4().hex


def wait_dossier(api: API, token: str, domain: str = DOMAIN, timeout: float = 300) -> dict:
    end, latest = time.monotonic() + timeout, None
    while time.monotonic() < end:
        response = api.get(f"/dossiers/{domain}", token=token)
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest.get("state") in ("ready", "failed"):
            return latest
        time.sleep(0.1)
    raise AssertionError(f"build did not finish: {latest}")


def create(api: API, token: str, domain: str = DOMAIN, *, idem: str | None = None) -> tuple[dict, requests.Response]:
    response = api.post("/dossiers", token=token, json={"domain": domain}, headers={"Idempotency-Key": idem or key()})
    assert response.status_code == 202, response.text
    return wait_dossier(api, token, domain), response


def refresh(api: API, token: str, domain: str = DOMAIN) -> dict:
    response = api.post(f"/dossiers/{domain}/refresh", token=token,
                        headers={"Idempotency-Key": key()})
    assert response.status_code == 202, response.text
    return wait_dossier(api, token, domain)


def wait_batch(api: API, token: str, batch_id: str, timeout: float = 300) -> dict:
    end, latest = time.monotonic() + timeout, None
    while time.monotonic() < end:
        response = api.get(f"/batches/{batch_id}", token=token)
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest.get("state") == "done":
            return latest
        time.sleep(0.1)
    raise AssertionError(f"batch did not finish: {latest}")


def history(api: API, token: str, domain: str = DOMAIN) -> dict:
    response = api.get(f"/dossiers/{domain}/history", token=token)
    assert response.status_code == 200, response.text
    return response.json()


def feed(api: API, token: str, since: int = 0, limit: int = 200) -> dict:
    response = api.get(f"/changes?since={since}&limit={limit}", token=token)
    assert response.status_code == 200, response.text
    return response.json()


def _drop(value: Any, keys: set[str]) -> Any:
    if isinstance(value, list):
        return [_drop(item, keys) for item in value]
    if isinstance(value, dict):
        return {name: _drop(item, keys) for name, item in value.items() if name not in keys}
    return value


def downgrade_export(export: dict, stage: int) -> dict:
    """Shape a current public export as a synthetic earlier-stage export."""
    old = dict(export)
    if stage == 1:
        remove = {"builds", "versions", "history", "feed", "seq", "executives", "investors", "candidates", "true_from", "learned_at", "origin", "origins", "corroborated", "corroborated_since"}
    elif stage == 2:
        remove = {"builds", "versions", "history", "feed", "seq", "executives", "investors", "true_from", "learned_at", "origin", "origins", "corroborated", "corroborated_since"}
    else:
        remove = {"investors", "origins", "corroborated", "corroborated_since", "origin"}
    old["state"] = _drop(export["state"], remove)
    if stage == 1:
        def normalize(value: Any) -> Any:
            if isinstance(value, list):
                return [normalize(item) for item in value]
            if not isinstance(value, dict):
                return value
            result = {name: normalize(item) for name, item in value.items()}
            if {"value", "status", "citations"} <= result.keys():
                result["status"] = "unknown" if result["value"] is None else "known"
            return result
        old["state"] = normalize(old["state"])
    return old


@pytest.fixture
def restart_container() -> str:
    name = os.environ.get("DOSSIER_CONTAINER", "")
    if not name:
        pytest.skip("set DOSSIER_CONTAINER to an explicitly disposable Stage 4 container")
    try:
        result = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("docker CLI unavailable; restart test not run")
    if result.returncode:
        pytest.skip(f"DOSSIER_CONTAINER {name!r} is not inspectable")
    return name


def wait_healthy(api: API, timeout: float = 90) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if api.get("/health", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.25)
    raise AssertionError("service did not become healthy after container restart")
