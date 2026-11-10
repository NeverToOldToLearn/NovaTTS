"""The bundled GUI must be able to call the backend.

Windows WebView2 serves the packaged frontend from ``http://tauri.localhost``
(not https, not ``tauri://localhost``). A missing origin here makes every
request fail silently in the GUI: no Qwen status, no voices, no games.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novatts.main import app

# A path that always answers, without needing the runtime to be started.
PROBE = "/__cors_probe__"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize(
    "origin",
    [
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
    ],
)
def test_gui_origins_allowed(client: TestClient, origin: str) -> None:
    res = client.get(PROBE, headers={"Origin": origin})
    assert res.headers.get("access-control-allow-origin") == origin


def test_preflight_allows_gui_origin(client: TestClient) -> None:
    res = client.options(
        "/status",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://tauri.localhost"


def test_unknown_origin_not_allowed(client: TestClient) -> None:
    res = client.get(PROBE, headers={"Origin": "http://evil.example"})
    assert res.headers.get("access-control-allow-origin") is None
