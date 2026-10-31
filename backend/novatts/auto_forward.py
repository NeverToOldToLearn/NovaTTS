"""Global auto-forward addon for RenPy games.

When a TTS line finishes playing, wait briefly and send a Space keystroke
to the game window so RenPy advances to the next line. Useful when a game
has auto-forward disabled: the voice becomes the metronome.

Platform notes:

Windows
  The hotkey is registered globally (Win32 RegisterHotKey); the spacebar
  is posted to the game window's HWND via PostMessage, so it never reaches
  other applications and never fires on clipboard copies.

Linux (X11)
  ``xdotool`` is used for both window search and keystroke injection. Works
  on X11 out of the box. In a Wayland session only X11/Xwayland windows are
  reachable, so an explicit target window is required; native Wayland clients
  have no stable way to receive synthetic input. Global hotkey toggle is not
  available on Linux — use the GUI toggle or the
  ``/auto-forward/toggle`` endpoint instead.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_SPACE = 0x20

_IS_WINDOWS = sys.platform == "win32"
_IS_LINUX = sys.platform.startswith("linux")
_HAS_XDOTOOL = bool(shutil.which("xdotool")) if _IS_LINUX else False
_IS_WAYLAND = bool(os.environ.get("WAYLAND_DISPLAY")) if _IS_LINUX else False
_HAS_DISPLAY = bool(os.environ.get("DISPLAY")) if _IS_LINUX else False


# --- Win32 helpers -----------------------------------------------------------

class _NoUser32:
    """Placeholder that makes auto-forward a no-op outside Windows."""

    def __getattr__(self, name: str) -> object:
        raise OSError(f"Win32 API {name} is unavailable on this platform")


if _IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wt

    # getattr keeps mypy happy on non-Windows, where ctypes has no `windll`.
    _USER32: Any = getattr(ctypes, "windll").user32  # noqa: B009
    _WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", None)
else:
    _USER32 = _NoUser32()
    _WINFUNCTYPE = None

_HOTKEY_VK = {
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74,
    "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
    "F11": 0x7A, "F12": 0x7B,
    "PAUSE": 0x13, "SCROLL": 0x91, "INSERT": 0x2D,
}

HOTKEY_OPTIONS = list(_HOTKEY_VK.keys())


class AutoForward:
    def __init__(
        self,
        *,
        hotkey: str = "F12",
        delay: float = 1.0,
        target: str = "",
        on_toggle: Callable[[bool], None] | None = None,
    ) -> None:
        self.enabled = False
        self.delay = max(0.1, float(delay))
        self.target = (target or "").strip().lower()
        self.on_toggle = on_toggle
        self._hotkey_name = hotkey.upper().strip() or "F9"
        self._hotkey_id = 0x4E56  # "NV"
        self._vk = _HOTKEY_VK.get(self._hotkey_name, 0x78)
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False

    # -- lifecycle ---------------------------------------------------

    def start(self) -> None:
        if _IS_WINDOWS:
            pass  # hotkey loop below
        elif _IS_LINUX:
            if not _HAS_XDOTOOL:
                log.info("auto-forward: xdotool not found — install it (apt install xdotool) for auto-forward on X11")
                return
            if not _HAS_DISPLAY:
                log.info("auto-forward: no DISPLAY — synthetic input needs an X11/Xwayland server; auto-forward disabled")
                return
            if _IS_WAYLAND:
                # The session is Wayland, but most games (SDL/Ren'Py) still run
                # as X11 clients under Xwayland. xdotool can reach those.
                log.info("auto-forward: Wayland session — only X11/Xwayland windows are reachable; set a target window")
        else:
            log.info("auto-forward: not supported on this platform")
            return
        if self._running:
            return
        self._running = True
        if _IS_WINDOWS:
            self._thread = threading.Thread(target=self._hotkey_loop, name="auto-forward-hotkey", daemon=True)
            self._thread.start()
        # On Linux there is no global hotkey loop — toggle via GUI or API.

    def stop(self) -> None:
        self._running = False
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        # Post a quit message to break GetMessage (Windows only).
        if _IS_WINDOWS:
            with contextlib.suppress(Exception):
                _USER32.PostThreadMessageW(self._thread.ident if self._thread else 0, 0x0012, 0, 0)  # WM_QUIT

    # -- toggle ------------------------------------------------------

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        if not self.enabled:
            with self._lock:
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
        log.info("auto-forward %s", "ON" if self.enabled else "OFF")
        if self.on_toggle is not None:
            try:
                self.on_toggle(self.enabled)
            except Exception:
                log.exception("on_toggle callback failed")
        return self.enabled

    def set_enabled(self, value: bool) -> None:
        if value == self.enabled:
            return
        self.toggle()

    def set_hotkey(self, name: str) -> bool:
        name = (name or "").upper().strip()
        if name not in _HOTKEY_VK:
            return False
        if name == self._hotkey_name:
            return True
        # Unregister current if registered.
        was_running = self._running
        if was_running:
            self._running = False
            with contextlib.suppress(Exception):
                _USER32.UnregisterHotKey(None, self._hotkey_id)
        self._hotkey_name = name
        self._vk = _HOTKEY_VK[name]
        if was_running:
            self._running = True
            # Re-register in a fresh thread.
            self._thread = threading.Thread(target=self._hotkey_loop, name="auto-forward-hotkey", daemon=True)
            self._thread.start()
        log.info("auto-forward: hotkey changed to %s", name)
        return True

    # -- spoken notification ----------------------------------------

    def notify_spoken(self) -> None:
        """Called when a TTS line finished playing naturally."""
        if not self.enabled:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            timer = threading.Timer(self.delay, self._advance)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def notify_after_stream(self, session: object) -> None:
        """Wait for a live stream to drain, then notify (if not aborted)."""
        if not self.enabled:
            return
        drained = getattr(session, "drained", None)
        aborted_attr = "aborted"

        def _wait() -> None:
            try:
                if drained is not None:
                    drained.wait(timeout=120.0)
            except Exception:
                return
            if getattr(session, aborted_attr, False):
                return
            self.notify_spoken()

        threading.Thread(target=_wait, name="auto-forward-stream-wait", daemon=True).start()

    # -- advance -----------------------------------------------------

    def capture_foreground(self) -> str:
        """Capture the currently foreground window's title as the target."""
        if _IS_WINDOWS:
            hwnd = _USER32.GetForegroundWindow()
            if not hwnd:
                return ""
            length = _USER32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            _USER32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title:
                self.target = title.lower()
            log.info("auto-forward: captured target %r (hwnd=%s)", title, hwnd)
            return title
        if _IS_LINUX and _HAS_XDOTOOL:
            try:
                proc = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True, text=True, timeout=5,
                )
                title = proc.stdout.strip()
                if title:
                    self.target = title.lower()
                log.info("auto-forward: captured target %r (xdotool)", title)
                return title
            except Exception:
                log.exception("auto-forward: xdotool capture failed")
        return ""

    def _advance(self) -> None:
        if not self.enabled:
            return
        if _IS_WINDOWS:
            self._advance_win32()
        elif _IS_LINUX and _HAS_XDOTOOL:
            self._advance_xdotool()
        else:
            return

    def _advance_win32(self) -> None:
        hwnd = self._find_window()
        if hwnd is None:
            log.info("auto-forward: no game window found (target=%r)", self.target)
            return
        fg = _USER32.GetForegroundWindow()
        log.info("auto-forward: advancing hwnd=%s fg=%s target=%r", hwnd, fg, self.target)
        try:
            if fg == hwnd:
                _USER32.keybd_event(VK_SPACE, 0x39, 0, 0)
                time.sleep(0.05)
                _USER32.keybd_event(VK_SPACE, 0x39, 0x0002, 0)
                log.info("auto-forward: keybd_event space sent (foreground)")
            else:
                _USER32.PostMessageW(hwnd, WM_KEYDOWN, VK_SPACE, 0x00000001)
                time.sleep(0.05)
                _USER32.PostMessageW(hwnd, WM_KEYUP, VK_SPACE, 0xC0000001)
                log.info("auto-forward: PostMessage space sent (background)")
        except Exception:
            log.exception("auto-forward: failed to send space")

    def _advance_xdotool(self) -> None:
        wid = self._find_window_xdotool()
        if wid is None:
            log.info("auto-forward: no game window found (target=%r)", self.target)
            return
        log.info("auto-forward: xdotool space → window %s", wid)
        try:
            proc = self._send_space_xdotool(wid)
            if proc.returncode != 0:
                log.warning(
                    "auto-forward: xdotool failed (exit %s): %s",
                    proc.returncode,
                    (proc.stderr or "").strip()[:200],
                )
        except Exception:
            log.exception("auto-forward: xdotool key failed")

    @staticmethod
    def _send_space_xdotool(wid: str) -> subprocess.CompletedProcess[str]:
        """Send Space to ``wid``.

        ``xdotool key --window`` uses XSendEvent, which SDL/Ren'Py windows
        routinely ignore. XTEST input (plain ``xdotool key``) does reach them,
        but only when the window has focus — and the game should have focus
        while auto-forwarding anyway.

        On Wayland the compositor's focus-stealing prevention makes
        ``windowactivate`` unreliable, and a "successful" activation can
        still leave keyboard focus elsewhere (so XTEST goes nowhere).
        There we never activate: XTEST when the target is already active,
        XSendEvent as a best-effort otherwise. On X11, activate first and
        fall back to XSendEvent when the window manager refuses.
        """

        def active() -> str:
            try:
                return subprocess.run(
                    ["xdotool", "getactivewindow"],
                    capture_output=True, text=True, timeout=2,
                ).stdout.strip()
            except Exception:
                return ""

        if active() == wid:
            return subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "space"],
                capture_output=True, text=True, timeout=5,
            )
        if not _IS_WAYLAND:
            try:
                activated = subprocess.run(
                    ["xdotool", "windowactivate", "--sync", wid],
                    capture_output=True, text=True, timeout=2,
                )
                if activated.returncode == 0 and active() == wid:
                    return subprocess.run(
                        ["xdotool", "key", "--clearmodifiers", "space"],
                        capture_output=True, text=True, timeout=5,
                    )
            except Exception:
                log.debug("auto-forward: windowactivate failed, using XSendEvent")
        return subprocess.run(
            ["xdotool", "key", "--window", wid, "space"],
            capture_output=True, text=True, timeout=5,
        )

    def test_advance(self) -> dict[str, object]:
        if _IS_WINDOWS:
            return self._test_advance_win32()
        if _IS_LINUX and _HAS_XDOTOOL and _HAS_DISPLAY:
            return self._test_advance_xdotool()
        return {"ok": False, "reason": "auto-forward is not supported on this platform"}

    # -- GUI / API helpers -------------------------------------------

    def status(self) -> dict[str, object]:
        """Everything the settings panel needs to render the toggle."""
        if _IS_WINDOWS:
            available = True
            reason = ""
        elif _IS_LINUX and not _HAS_XDOTOOL:
            available = False
            reason = "xdotool not installed (apt install xdotool)"
        elif _IS_LINUX and not _HAS_DISPLAY:
            available = False
            reason = "no X11/Xwayland display; synthetic input is unavailable"
        elif _IS_LINUX:
            available = True
            reason = (
                "Wayland session: only X11/Xwayland windows are visible — "
                "set a target window title"
                if _IS_WAYLAND
                else ""
            )
        else:
            available = False
            reason = "auto-forward is not supported on this platform"
        return {
            "enabled": self.enabled,
            "target": self.target,
            "delay": self.delay,
            "hotkey": self._hotkey_name,
            "platform": "windows" if _IS_WINDOWS else "linux" if _IS_LINUX else sys.platform,
            "wayland": _IS_WAYLAND,
            "xdotool": _HAS_XDOTOOL,
            "available": available,
            "reason": reason,
            "can_capture": _IS_WINDOWS or (_IS_LINUX and _HAS_XDOTOOL and _HAS_DISPLAY),
            "can_test": available,
        }

    def list_windows(self) -> list[str]:
        """Visible window titles xdotool can reach (X11/Xwayland only)."""
        if not (_IS_LINUX and _HAS_XDOTOOL and _HAS_DISPLAY):
            return []
        try:
            proc = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--name", ".*"],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            log.exception("auto-forward: xdotool window list failed")
            return []
        if proc.returncode != 0:
            return []
        titles: list[str] = []
        for wid in proc.stdout.split():
            try:
                name = subprocess.run(
                    ["xdotool", "getwindowname", wid],
                    capture_output=True, text=True, timeout=2,
                ).stdout.strip()
            except Exception:
                continue
            # Mutter's guard window is an implementation detail, and empty
            # titles cannot be matched by the user anyway.
            if not name or name == "mutter guard window":
                continue
            if name not in titles:
                titles.append(name)
        return sorted(titles)


    def _test_advance_win32(self) -> dict[str, object]:
        hwnd = self._find_window()
        if hwnd is None:
            return {"ok": False, "reason": f"no window matched target {self.target!r}"}
        fg = _USER32.GetForegroundWindow()
        try:
            if fg == hwnd:
                _USER32.keybd_event(VK_SPACE, 0x39, 0, 0)
                time.sleep(0.05)
                _USER32.keybd_event(VK_SPACE, 0x39, 0x0002, 0)
                return {"ok": True, "method": "keybd_event", "hwnd": hwnd, "foreground": fg, "target": self.target}
            _USER32.PostMessageW(hwnd, WM_KEYDOWN, VK_SPACE, 0x00000001)
            time.sleep(0.05)
            _USER32.PostMessageW(hwnd, WM_KEYUP, VK_SPACE, 0xC0000001)
            return {"ok": True, "method": "PostMessage", "hwnd": hwnd, "foreground": fg, "target": self.target}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    def _test_advance_xdotool(self) -> dict[str, object]:
        wid = self._find_window_xdotool()
        if wid is None:
            return {"ok": False, "reason": f"no window matched target {self.target!r}"}
        try:
            proc = self._send_space_xdotool(wid)
            if proc.returncode == 0:
                return {"ok": True, "method": "xdotool", "wid": wid, "target": self.target}
            return {"ok": False, "reason": f"xdotool exit {proc.returncode}: {proc.stderr[:200]}"}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    def _find_window(self) -> int | None:
        if not _IS_WINDOWS:
            return None
        target = self.target
        # If no explicit target, try to find a Ren'Py/game window by title,
        # falling back to the foreground window.
        effective_target = target
        if not effective_target:
            effective_target = ""  # handled below
        results: list[int] = []
        seen_titles: list[str] = []
        if _WINFUNCTYPE is None:
            return None

        @_WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)  # type: ignore[untyped-decorator]
        def enum_proc(hwnd: int, _lparam: int) -> bool:
            if not _USER32.IsWindowVisible(hwnd):
                return True
            length = _USER32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            _USER32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if not title:
                return True
            low = title.lower()
            if target:
                seen_titles.append(title)
                if target in low:
                    results.append(hwnd)
            else:
                if "renpy" in low or hwnd == _USER32.GetForegroundWindow():
                    results.append(hwnd)
                    seen_titles.append(title)
            return True

        try:
            _USER32.EnumWindows(enum_proc, 0)
        except Exception:
            log.exception("auto-forward: EnumWindows failed")
            return None
        if not results:
            log.info("auto-forward: no match; visible titles: %s", seen_titles[:20])
        elif target:
            log.info("auto-forward: matched %d windows for target %r", len(results), target)
        return results[0] if results else None

    @staticmethod
    def _is_x11_frame(wid: str) -> bool:
        """True for mutter's Xwayland frame windows.

        Every Xwayland client has a sibling frame window owned by
        ``mutter-x11-frames``. It carries the same title, but keyboard events
        sent to it disappear. ``xprop`` may be absent; then we keep the
        candidate rather than dropping every match.
        """
        try:
            proc = subprocess.run(
                ["xprop", "-id", wid, "WM_CLASS"],
                capture_output=True, text=True, timeout=2,
            )
        except Exception:
            return False
        return "mutter-x11-frames" in proc.stdout

    def _find_window_xdotool(self) -> str | None:
        """Find a game window using xdotool on X11."""
        target = self.target
        try:
            if target:
                proc = subprocess.run(
                    ["xdotool", "search", "--onlyvisible", "--name", target],
                    capture_output=True, text=True, timeout=5,
                )
                wids = proc.stdout.split()
                if wids:
                    # Xwayland wraps each client in a separate mutter frame
                    # window that shares the title but never receives input.
                    # Sending there is a silent no-op, so prefer the client.
                    for candidate in wids:
                        if not self._is_x11_frame(candidate):
                            log.info("auto-forward: xdotool found window %s for target %r", candidate, target)
                            return candidate
                    log.info("auto-forward: only mutter frame windows matched %r", target)
                    return None
            else:
                # Under Wayland only X11/Xwayland windows are visible to
                # xdotool; guessing the "active" window could hit an unrelated
                # X11 app. Require an explicit target there.
                if _IS_WAYLAND:
                    log.info("auto-forward: Wayland session — capture/set a target window first")
                    return None
                # Try renpy first, then fall back to the active window.
                proc = subprocess.run(
                    ["xdotool", "search", "--name", "renpy"],
                    capture_output=True, text=True, timeout=5,
                )
                if proc.returncode != 0 or not proc.stdout.strip():
                    proc = subprocess.run(
                        ["xdotool", "getactivewindow"],
                        capture_output=True, text=True, timeout=5,
                    )
            if proc.returncode == 0 and proc.stdout.strip():
                wid = proc.stdout.strip().splitlines()[0]
                log.info("auto-forward: xdotool found window %s for target %r", wid, target)
                return wid
        except Exception:
            log.exception("auto-forward: xdotool search failed")
        log.info("auto-forward: xdotool found no window for target %r", target)
        return None

    # -- hotkey loop -------------------------------------------------

    def _hotkey_loop(self) -> None:
        if not _IS_WINDOWS:
            return
        if not _USER32.RegisterHotKey(None, self._hotkey_id, 0, self._vk):
            log.warning("auto-forward: RegisterHotKey failed for %s", self._hotkey_name)
            return
        log.info("auto-forward: hotkey %s registered", self._hotkey_name)
        msg = wt.MSG()
        while self._running:
            ret = _USER32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                self.toggle()
            _USER32.TranslateMessage(ctypes.byref(msg))
            _USER32.DispatchMessageW(ctypes.byref(msg))
        _USER32.UnregisterHotKey(None, self._hotkey_id)
        log.info("auto-forward: hotkey unregistered")
