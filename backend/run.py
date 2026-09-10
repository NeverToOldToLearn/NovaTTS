"""NovaTTS launcher.

Run from anywhere inside the repo:

    python run.py

or

    python -m novatts.main          (from the backend/ directory)
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

# Make the backend/ directory importable when run as a plain script.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from novatts.config import settings  # noqa: E402

def _run() -> None:
    import argparse

    from novatts.main import app as _app

    p = argparse.ArgumentParser()
    p.add_argument("--host", default=None)
    p.add_argument("--port", default=None)
    a, _ = p.parse_known_args()
    host = a.host or settings.host
    try:
        port = int(a.port) if a.port is not None else settings.port
    except Exception:
        port = settings.port
    print(f"NovaTTS starting on http://{host}:{port}")
    uvicorn.run(_app, host=host, port=port)


if __name__ == "__main__":
    _run()
