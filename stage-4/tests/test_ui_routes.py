"""Browser routes: a static shell with no data; the API keeps its JSON and its auth."""
import pytest
from starlette.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeWeb

BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


@pytest.fixture
def client():
    with TestClient(create_app(web_factory=FakeWeb)) as c:
        c.post("/_test/reset", json={"now": "2026-03-01T09:00:00+00:00", "users": []})
        yield c


@pytest.mark.parametrize("path", ["/", "/signup", "/login", "/contested",
                                  "/dossiers/acme-robotics.test",
                                  "/dossiers/WWW.Acme-Robotics.TEST/evidence"])
def test_screens_are_the_shell_without_a_token(client, path):
    r = client.get(path, headers=BROWSER)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "/static/app.js" in r.text and "acme" not in r.text.lower()


def test_evidence_route_is_the_shell_whatever_it_accepts(client):
    r = client.get("/dossiers/acme-robotics.test/evidence")
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("headers", [{}, {"Accept": "application/json"}, {"Accept": "*/*"}])
def test_api_requests_get_json_and_need_a_token(client, headers):
    r = client.get("/dossiers/acme-robotics.test", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_static_assets_and_no_escape(client):
    js = client.get("/static/app.js")
    assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
    assert client.get("/static/screens/dossier.js").status_code == 200
    assert client.get("/static/styles.css").headers["content-type"].startswith("text/css")
    assert client.get("/static/../main.py").status_code == 404
    assert client.get("/static/%2e%2e/main.py").status_code == 404
    assert client.get("/static/nope.js").status_code == 404


def test_ui_has_no_external_assets():
    from pathlib import Path
    for path in (Path(__file__).parent.parent / "app" / "ui").rglob("*"):
        if path.is_file():
            text = path.read_text()
            assert "https://" not in text and "http://" not in text, path
