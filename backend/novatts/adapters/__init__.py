"""Input adapters package.

One package, three routes to the same raw line. ``LunaAdapter`` (the hook) is
the default since F8; ``ClipboardAdapter`` (RenPy) is legacy and kept working;
``FileMonitorAdapter`` is a tailer over the hook's parser rather than a route
of its own, which is why it is not a peer here.

``__all__`` stays alphabetical because a linter reads that list far more often
than a human does.
"""

from .base import InputAdapter
from .file_monitor import FileMonitorAdapter
from .legacy_clipboard import ClipboardAdapter
from .luna import HookTextProcessor, LunaAdapter, decode_wire_message

__all__ = [
    "ClipboardAdapter",
    "FileMonitorAdapter",
    "HookTextProcessor",
    "InputAdapter",
    "LunaAdapter",
    "decode_wire_message",
]
