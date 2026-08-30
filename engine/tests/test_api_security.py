"""Response headers.

A decision-support tool for a public agency ends up embedded in intranet
portals and proxied behind things nobody audits, so the defaults matter more
than usual.
"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from nullsignal.api.security import BASE_HEADERS, SecurityHeadersMiddleware


@pytest.fixture
def client():
    app = Starlette(routes=[Route("/probe", lambda r: JSONResponse({"ok": True}))])
    app.add_middleware(SecurityHeadersMiddleware)
    return TestClient(app, base_url="http://testserver")


def test_every_required_header_is_present(client):
    headers = client.get("/probe").headers
    for name, value in BASE_HEADERS.items():
        assert headers.get(name) == value, name


def test_the_api_declares_that_it_serves_no_active_content(client):
    """This service answers with JSON and nothing else -- no scripts, no
    frames, no embedded media. Saying so is cheaper than hoping."""
    policy = client.get("/probe").headers["Content-Security-Policy"]
    assert "default-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy


def test_verdicts_are_not_cached_by_intermediaries(client):
    """Every response names a neighbourhood and a moment. Neither is public,
    and neither stays true."""
    assert client.get("/probe").headers["Cache-Control"] == "no-store"


def test_hsts_is_withheld_over_plain_http(client):
    """Emitting it over HTTP is ignored at best. At worst a developer copies
    the config to a host that cannot serve TLS, and the browser then refuses
    the only scheme that works."""
    assert "Strict-Transport-Security" not in client.get("/probe").headers


def test_hsts_is_sent_over_tls():
    app = Starlette(routes=[Route("/probe", lambda r: JSONResponse({"ok": True}))])
    app.add_middleware(SecurityHeadersMiddleware)
    secure = TestClient(app, base_url="https://testserver")

    header = secure.get("/probe").headers.get("Strict-Transport-Security")
    assert header and "max-age=31536000" in header
    assert "includeSubDomains" in header


def test_a_handler_may_override_a_default(client):
    """setdefault, not assignment: a route that needs its own policy should be
    able to say so without editing the middleware."""
    app = Starlette(routes=[Route(
        "/probe",
        lambda r: JSONResponse({"ok": True}, headers={"Cache-Control": "max-age=60"}),
    )])
    app.add_middleware(SecurityHeadersMiddleware)
    assert TestClient(app).get("/probe").headers["Cache-Control"] == "max-age=60"


def test_the_static_build_carries_the_policy_the_server_sets_in_middleware():
    """The deployed site has no middleware in front of it.

    The header section of the README used to claim "every response" carries a
    CSP. That was true of the API and false of the published build, which is
    the one anybody opens: it was sending nothing but the host's own HSTS. A
    document can carry a policy in `<meta>`, so it does, and this fails if the
    tag is dropped or loosened.
    """
    from pathlib import Path

    index = Path(__file__).resolve().parents[2] / "web" / "index.html"
    if not index.exists():
        pytest.skip("web sources not present")

    html = index.read_text()
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "default-src 'none'" in html
    assert "script-src 'self'" in html, "scripts must not be given a wildcard"
    assert "'unsafe-eval'" not in html
    # The one concession, and only for styles: bar widths are style attributes.
    assert "'unsafe-inline'" in html.split("style-src")[1].split(";")[0]
    assert "'unsafe-inline'" not in html.split("script-src")[1].split(";")[0]
