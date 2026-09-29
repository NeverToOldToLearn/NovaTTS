"""Test isolation for the input route. Added in F14.

Nine tests in ``test_luna_adapter.py`` went red on an untouched commit. The
cause was not the code under test: this machine's ``backend/.env`` held

    NOVATTS_LUNA_WS_URL=NOVATTS_LUNA_WS_URL=ws://127.0.0.1:6677

A non-empty ``luna_ws_url`` is what selects client mode over server mode
(``if self.ws_url`` in the adapter), so every ``LunaAdapter`` built by the
test session became a dialling client, the server never bound, and the
server-mode tests failed with ``ConnectionRefusedError``. Reproduced 3 runs
out of 3 on the unmodified source.

A suite whose verdict depends on one developer's desktop is not a gate. This
fixture pins every hook-input setting to the declared default, so a test run
reports on the code. A test that needs a different value sets it itself with
``monkeypatch`` inside the test, which runs after this fixture and therefore
wins. ``test_hook_config.py::test_the_suite_does_not_see_the_developers_env``
pins that the isolation is real: a harness that reports "nothing found" is
only evidence once its own comparison has been shown to fire.

Pinning to ``Settings.model_fields[...].default`` rather than to a
hand-written list of values means a new hook setting is covered the day it
is added, without editing this file.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from novatts.config import Settings, settings

#: Every setting the input adapters read at construction time. These are the
#: ones that can change what a test exercises without changing the test.
HOOK_INPUT_FIELDS = (
    "hook_host",
    "hook_port",
    "hook_mode",
    "hook_space_form",
    "hook_dual_hook",
    "luna_ws_url",
    "file_watch",
    "file_watch_path",
    "dedup_window_ms",
    "min_text_length",
)


@pytest.fixture(autouse=True)
def _pin_hook_input_settings() -> Iterator[None]:
    """Reset hook-input settings to their defaults around every test."""
    missing = [f for f in HOOK_INPUT_FIELDS if f not in Settings.model_fields]
    assert not missing, f"HOOK_INPUT_FIELDS names fields Settings does not have: {missing}"

    saved = {f: getattr(settings, f) for f in HOOK_INPUT_FIELDS}
    for field in HOOK_INPUT_FIELDS:
        setattr(settings, field, Settings.model_fields[field].default)
    try:
        yield
    finally:
        for field, value in saved.items():
            setattr(settings, field, value)
