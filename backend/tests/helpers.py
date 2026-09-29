"""Importable test helpers. Not a test module -- no ``test_`` prefix.

Kept out of ``conftest.py`` on purpose: pytest puts this directory on
``sys.path[0]`` (importmode=prepend, and there is no ``__init__.py``), so a
plain module is importable by name, while conftest is not.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from novatts.config import Settings

#: The ``NOVATTS_*`` variables this machine exported when the test session
#: started. This is the developer's desktop. A variable set *later*, by
#: monkeypatch, is the test's own and must survive -- see
#: :func:`_no_novatts_env`. Snapshot taken at import, because by the time a
#: test runs it is too late to tell the two apart.
_AMBIENT: dict[str, str] = {
    key: value for key, value in os.environ.items() if key.startswith("NOVATTS_")
}


@contextmanager
def _no_novatts_env() -> Iterator[None]:
    """Hide the ambient ``NOVATTS_*`` variables for the duration of a block.

    "Ambient" is the whole point, and the first version of this deleted
    every ``NOVATTS_*`` key it could see -- which also deleted the variable
    the calling test had just set, so ``test_hook_env_vars_are_read`` failed
    on all nine of its parameters. A helper that removes the thing under
    test is not a helper.

    So a key is hidden only when it is still the desktop's value. If a test
    changed it, that is the test talking and it stays. The remaining gap is
    a test setting a key to exactly the ambient value, which then reads as
    ambient and is hidden; that test would be asserting the default anyway,
    so it still passes, and it is documented rather than defended against.
    """
    hidden: dict[str, str] = {}
    for key, ambient_value in _AMBIENT.items():
        if os.environ.get(key) == ambient_value:
            hidden[key] = ambient_value
            del os.environ[key]
    try:
        yield
    finally:
        os.environ.update(hidden)


def make_settings(**overrides: object) -> Settings:
    """A Settings instance built as if the machine had no NovaTTS config.

    F14. Two sources have to go, and forgetting either one is the bug this
    exists to prevent:

      * ``backend/.env`` -- pydantic-settings reads the file itself, so
        clearing ``os.environ`` does not help. ``_env_file=None`` does.
      * ``NOVATTS_*`` in the environment -- the same settings reached by
        another route, and what a developer who exported them by hand has.

    Without this, a test asserting a *default* was really asserting "the
    default, unless someone's desktop says otherwise". That is not a test
    bug in the abstract: it is how ``test_hook_defaults_match_the_agreed_
    topology`` failed on a machine whose .env set NOVATTS_HOOK_MODE, and how
    nine ``test_luna_adapter.py`` tests failed on an untouched commit
    because this machine's .env held a doubled NOVATTS_LUNA_WS_URL.

    Tests that need a value set it with ``monkeypatch.setenv``, which still
    works: pydantic keeps reading ``os.environ``, we only stop it from
    reading the rest of the desktop.
    """
    with _no_novatts_env():
        return Settings(_env_file=None, **overrides)
