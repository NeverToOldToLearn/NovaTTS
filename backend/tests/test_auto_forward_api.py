"""Route contract for the auto-forward API.

The GUI and the frozen backend ship as separate binaries, so a renamed route
shows up as a 404 in the settings panel. Keep both the current paths and the
older aliases registered.
"""

from __future__ import annotations

from novatts.main import app


def _paths() -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def test_auto_forward_routes_registered() -> None:
    paths = _paths()
    assert "/auto-forward" in paths
    assert "/auto-forward/toggle" in paths
    assert "/auto-forward/capture" in paths
    assert "/auto-forward/windows" in paths
    assert "/auto-forward/test" in paths


def test_auto_forward_legacy_aliases_registered() -> None:
    paths = _paths()
    assert "/auto-forward/status" in paths
    assert "/auto-forward/config" in paths
