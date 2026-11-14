"""HTTP-only helpers for independent Stage 3 acceptance checks."""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
import requests


BASE_URL = os.environ.get("DOSSIER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
TEST_DOMAIN = os.environ.get("DOSSIER_TEST_DOMAIN", "halvorsen-robotics.test")
NOW = "2026-03-01T09:00:00+00:00"
ALICE = {"id": "s3_accept_ada", "email": "ada.s3@example.test",
         "password": "correct horse battery", "display_name": "Ada Stage Three"}
BOB = {"id": "s3_accept_bob", "email": "bob.s3@example.test",
       "password": "correct horse battery", "display_name": "Bob Stage Three"}
FIELDS = ("legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total")
FIELDS7 = FIELDS + ("executives",)
TITLE_ORDER = {"cfo": 0, "coo": 1, "cto": 2}
PROVIDER_ORDER = {name: i for i, name in enumerate(("nimble", "tavily", "kernel", "browserbase"))}
KIND_AUTHORITY = {"own": 0, "filing": 0, "news": 1, "aggregator": 2, None: 2}


@dataclass
class API:
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


class MockAdmin:
    """Optional harness mock control/log interface; assertions skip when absent."""

    def __init__(self) -> None:
        self.url = os.environ.get("DOSSIER_MOCK_URL", "").rstrip("/")
        self.token = os.environ.get("DOSSIER_MOCK_TOKEN", "")
        self.enabled = bool(self.url and self.token)

    def request(self, method: str, path: str, *, body: dict | None = None) -> dict | None:
        if not self.enabled:
            return None
        response = requests.request(method, self.url + path,
                                    headers={"X-Mock-Admin": self.token},
                                    json=body, timeout=10)
        assert response.status_code in (200, 204), response.text
        return response.json() if response.content else None

    def reset(self) -> None:
        self.request("POST", "/_mock/reset", body={"epoch": 0})

    def fault(self, provider: str, methods: list[str], mode: str) -> None:
        self.request("POST", "/_mock/faults", body={"provider": provider,
                                                       "methods": methods, "mode": mode})

    def calls(self) -> list[dict]:
        result = self.request("GET", "/_mock/log")
        return result["calls"] if result else []


@pytest.fixture(scope="session")
def api() -> API:
    return API()


@pytest.fixture(autouse=True)
def reset_state(api: API) -> None:
    response = api.post("/_test/reset", json={"now": NOW, "users": [ALICE, BOB]}, timeout=10)
    assert response.status_code == 204, response.text
    mock = MockAdmin()
    if mock.enabled:
        mock.reset()


@pytest.fixture
def token(api: API) -> str:
    return api.login(ALICE)


@pytest.fixture
def mock_admin() -> MockAdmin:
    return MockAdmin()


def new_key() -> str:
    return "stage3-accept-" + uuid.uuid4().hex


def parse_instant(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert dt.tzinfo is not None and dt.utcoffset() is not None, value
    return dt


def collapsed(text: str) -> str:
    return " ".join(text.split())


def stage2_rank_key(candidate: dict) -> tuple:
    """The public Stage 2 ranking rule, copied from the requirements."""
    published = candidate.get("published_at")
    instant = parse_instant(published).timestamp() if published else None
    value = candidate["value"]
    if isinstance(value, int) and not isinstance(value, bool):
        value_key = (0, value)
    else:
        value_key = (1, value.strip() if isinstance(value, str) else str(value))
    return (KIND_AUTHORITY.get(candidate.get("kind"), 2), instant is None,
            -(instant or 0), tuple(map(ord, candidate["url"])),
            PROVIDER_ORDER[candidate["provider"]], value_key)


def wait_dossier(api: API, token: str, domain: str, *, timeout: float = 300) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = api.get(f"/dossiers/{domain}", token=token)
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("state") in ("ready", "failed"):
            return last
        time.sleep(0.1)
    raise AssertionError(f"build for {domain} did not finish: {last}")


def create_build(api: API, token: str, domain: str = TEST_DOMAIN,
                 key: str | None = None) -> tuple[dict, requests.Response]:
    response = api.post("/dossiers", token=token, json={"domain": domain},
                        headers={"Idempotency-Key": key or new_key()})
    assert response.status_code == 202, response.text
    return wait_dossier(api, token, domain), response


def refresh_build(api: API, token: str, domain: str = TEST_DOMAIN,
                  key: str | None = None) -> tuple[dict, requests.Response]:
    response = api.post(f"/dossiers/{domain}/refresh", token=token,
                        headers={"Idempotency-Key": key or new_key()})
    assert response.status_code == 202, response.text
    return wait_dossier(api, token, domain), response


def set_clock(api: API, timestamp: str) -> None:
    response = api.post("/_test/clock", json={"now": timestamp})
    assert response.status_code == 204, response.text


def history(api: API, token: str, domain: str) -> dict:
    response = api.get(f"/dossiers/{domain}/history", token=token)
    assert response.status_code == 200, response.text
    return response.json()


def feed(api: API, token: str, since: int = 0, limit: int = 200) -> dict:
    response = api.get(f"/changes?since={since}&limit={limit}", token=token)
    assert response.status_code == 200, response.text
    return response.json()


def assert_history_entry(entry: dict) -> None:
    assert entry["type"] in ("initial", "change", "correction")
    assert "value" in entry and "true_from" in entry and "learned_at" in entry
    assert isinstance(entry["citations"], list)
    parse_instant(entry["learned_at"])
    if entry["value"] is None:
        assert entry["true_from"] is None and entry["citations"] == []


def stage1_shaped_export(export: dict) -> dict:
    """Downgrade an exported snapshot to the Stage 1 field shape for migration testing."""
    def convert(value: Any) -> Any:
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        out = {}
        for key, item in value.items():
            if key in {"executives", "builds", "versions", "history", "feed", "seq",
                       "true_from", "learned_at", "candidates"}:
                continue
            out[key] = convert(item)
        if {"value", "status", "citations"} <= out.keys():
            out["status"] = "unknown" if out["value"] is None else "known"
        return out

    result = {key: value for key, value in export.items()}
    result["state"] = convert(export["state"])
    return result


def stage2_shaped_export(export: dict) -> dict:
    """Downgrade Stage 3-only fields while preserving Stage 2 candidate records."""
    def convert(value: Any) -> Any:
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        out = {}
        for key, item in value.items():
            if key in {"executives", "builds", "versions", "history", "feed", "seq",
                       "true_from", "learned_at"}:
                continue
            out[key] = convert(item)
        return out

    result = {key: value for key, value in export.items()}
    result["state"] = convert(export["state"])
    return result


def wait_healthy(api: API, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = api.get("/health", timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.25)
    raise AssertionError("service did not become healthy after container restart")


@pytest.fixture
def restart_container() -> str:
    name = os.environ.get("DOSSIER_CONTAINER", "")
    if not name:
        pytest.skip("set DOSSIER_CONTAINER to an explicitly disposable Stage 3 container")
    try:
        probe = subprocess.run(["docker", "inspect", name], capture_output=True,
                               text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("docker CLI unavailable; restart survival test not run")
    if probe.returncode:
        pytest.skip(f"DOSSIER_CONTAINER {name!r} is not inspectable")
    return name
