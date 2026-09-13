"""Tests for the raw clipboard logger."""

from novatts.adapters.rawclipboard import RawClipboardLogger


def test_logs_full_raw_text(tmp_path):
    path = tmp_path / "clipboard_raw.log"
    logger = RawClipboardLogger(path, enabled=True)
    logger.log_entry("Rick: Aaaah, hmm, okay.", "OK")
    logger.log_entry("aaaaaaaah", "BLOCKED:too_short")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    # Format: <timestamp>  <status>  <raw>
    assert lines[0].endswith("  OK  Rick: Aaaah, hmm, okay.")
    assert lines[1].endswith("  BLOCKED:too_short  aaaaaaaah")


def test_disabled_writes_nothing(tmp_path):
    path = tmp_path / "clipboard_raw.log"
    RawClipboardLogger(path, enabled=False).log_entry("Hello.", "OK")
    assert not path.exists()


def test_clear_removes_file(tmp_path):
    path = tmp_path / "clipboard_raw.log"
    logger = RawClipboardLogger(path, enabled=True)
    logger.log_entry("Rick: okay.", "OK")
    assert path.exists()
    logger.clear()
    assert not path.exists()  # same policy as generated .wav cache
    # clear on a missing file is a no-op
    logger.clear()
