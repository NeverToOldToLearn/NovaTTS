"""Logging setup shared by all NovaTTS entrypoints.

Uvicorn's default logconfig only wires handlers onto its OWN loggers
(uvicorn / uvicorn.error / uvicorn.access); application loggers under
``novatts.*`` are left at WARNING with no handler, so their info/debug
messages never reach the console. Calling :func:`setup_logging` once at
startup (from ``run.py`` or ``novatts.main:__main__``, i.e. both the dev
launcher and the PyInstaller-built backend binary) fixes that.
"""

from __future__ import annotations

import logging

from .config import settings

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(*, level: str | None = None, format_: str = _DEFAULT_FORMAT) -> None:
    """Configure the root logger, honouring ``settings.log_level``.

    ``force=True`` makes this idempotently correct per entrypoint even if a
    previous caller already configured logging (e.g. uvicorn pulling in the
    app module before ``__main__`` runs).
    """
    level_name = (level or settings.log_level).strip().upper() or "INFO"
    resolved = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=resolved, format=format_, force=True)
    logging.getLogger("novatts").setLevel(resolved)
