"""Raw clipboard logger.

Writes ONE line per clipboard capture, with the FULL raw text, to a
plain file. This is the pre-filter source for regex/filter tuning: when a
text (e.g. a variable "aaaaah" variant) isn't caught, the exact pasted
text is right there to copy out of the log and build a pattern on.

Format (single line, no tabs/newlines lost):
    YYYY-MM-DD HH:MM:SS.mmm  <status>  <raw text>

``<status>`` is one of:
- OK              dialed the parser (may still be narration/skipped later)
- BLOCKED:...     rejected before parsing (see the reason)
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


class RawClipboardLogger:
    """Append raw clipboard captures to a plain UTF-8 log file."""

    def __init__(self, path: str | Path, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled
        if self.enabled:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                log.exception("Cannot create raw clipboard log dir %s", self.path.parent)

    def log_entry(self, raw: str, status: str) -> None:
        """Append one entry. ``status`` describes the pipeline outcome."""
        if not self.enabled:
            return
        from datetime import datetime

        line = f"{datetime.now():%Y-%m-%d %H:%M:%S.%f}  {status}  {raw}\n"
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            log.exception("Failed writing raw clipboard log %s", self.path)

    def clear(self) -> None:
        """Delete the log file (called on clean shutdown, like the audio cache)."""
        if not self.enabled:
            return
        try:
            if self.path.exists():
                self.path.unlink()
                log.info("Raw clipboard log cleared: %s", self.path)
        except OSError:
            log.exception("Failed clearing raw clipboard log %s", self.path)
