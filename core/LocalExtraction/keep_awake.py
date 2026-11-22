# LocalExtraction/keep_awake.py
"""Keep the computer awake while a long step runs (a search, a download, an extraction): no idle sleep, no screen
sleep, for as long as it is on, in every window of the program at once. Turned off when asked, and always when the
program ends.

  - macOS: the system's own `caffeinate` (display, idle and system sleep), tied to this program's process, so it
    ends with it even after a crash;
  - Windows: SetThreadExecutionState (system and display required), the documented way to say "work is under way";
  - Linux: `systemd-inhibit` holding an idle-and-sleep lock, where systemd is there.

What it cannot do: stop a laptop from sleeping when its lid is closed (macOS keeps that rule, unless the computer
is on power with an external display), nor keep a computer awake that is shut down or out of battery."""

import atexit
import logging
import os
import shutil
import subprocess
import sys
import threading
from typing import Callable, List, Optional

_ES_CONTINUOUS, _ES_SYSTEM_REQUIRED, _ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002


def until_gone(pid: int) -> List[str]:
    """A command that lasts as long as process `pid` (Linux): what systemd-inhibit holds its lock for, so the lock
    ends with the program even if it is killed or crashes (as `caffeinate -w` does on macOS)."""
    return ["sh", "-c", f"while kill -0 {pid} 2>/dev/null; do sleep 5; done"]


class KeepAwake:
    """One switch for the whole program. `listen(callback)`: told `callback(on)` whenever it changes, so every
    window's switch shows the same state."""

    def __init__(self, platform: str = sys.platform):
        self.platform = platform
        self._process: Optional[subprocess.Popen] = None
        self._on = False
        self._lock = threading.Lock()
        self._listeners: List[Callable[[bool], None]] = []

    @property
    def on(self) -> bool:
        return self._on

    def supported(self) -> bool:
        if self.platform == "darwin":
            return shutil.which("caffeinate") is not None
        if self.platform.startswith("win"):
            return True
        return shutil.which("systemd-inhibit") is not None

    def how(self) -> str:
        """What keeps the computer awake here, in a few words (for the switch's hint)."""
        if self.platform == "darwin":
            return "macOS caffeinate"
        if self.platform.startswith("win"):
            return "Windows power request"
        return "systemd-inhibit"

    def set(self, on: bool) -> bool:
        """Turns it on or off. Returns the state reached (off when this computer offers no way)."""
        with self._lock:
            if on and not self._on:
                self._on = self._start()
            elif not on and self._on:
                self._stop()
                self._on = False
            state = self._on
        for listener in list(self._listeners):
            try:
                listener(state)
            except Exception:  # a closed window's switch: forgotten
                self._listeners.remove(listener)
        return state

    def listen(self, callback: Callable[[bool], None]) -> Callable[[], None]:
        """Adds a listener; returns the function that removes it."""
        self._listeners.append(callback)
        return lambda: callback in self._listeners and self._listeners.remove(callback)

    # ------------------------------------------------------------------
    def _start(self) -> bool:
        try:
            if self.platform == "darwin":
                tool = shutil.which("caffeinate")
                if not tool:
                    return False
                # -d display, -i idle, -m disk, -s system (on power); -w: ends with this program, crash or not.
                self._process = subprocess.Popen([tool, "-dims", "-w", str(os.getpid())],
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif self.platform.startswith("win"):
                import ctypes
                if not ctypes.windll.kernel32.SetThreadExecutionState(
                        _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED):
                    return False
            else:
                tool = shutil.which("systemd-inhibit")
                if not tool:
                    return False
                self._process = subprocess.Popen(
                    [tool, "--what=idle:sleep", "--who=MoukhlijMatExtract", "--why=A long step is running",
                     "--mode=block", *until_gone(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as error:
            logging.warning(f"The computer cannot be kept awake: {error}")
            self._process = None
            return False
        logging.info(f"Keep awake: on ({self.how()}) — the computer will not go to sleep while it is on.")
        return True

    def _stop(self) -> None:
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        elif self.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
            except Exception:
                pass
        logging.info("Keep awake: off — the computer may sleep again as usual.")


AWAKE = KeepAwake()
atexit.register(lambda: AWAKE.set(False))
