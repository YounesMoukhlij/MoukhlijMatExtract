# LocalExtraction/gui/tkthreads.py
"""Tk variables are released on the main thread only.

Python's garbage collector can free a window's StringVar / BooleanVar on whichever thread happens to
be running — an extraction or a download thread. Releasing it there means a call into Tcl from that
thread: it waits for the main thread, and fails ("main thread is not in main loop") once the window's
loop has ended. `install(root)` makes such a release wait in a queue that the main thread empties."""

import queue
import threading
import tkinter as tk

_LATER: "queue.SimpleQueue" = queue.SimpleQueue()
_original = tk.Variable.__del__
_EVERY_MS = 2000


def _release(variable: tk.Variable) -> None:
    if threading.current_thread() is threading.main_thread():
        _original(variable)
    elif getattr(variable, "_tk", None) is not None:
        _LATER.put((variable._tk, variable._name, variable._tclCommands))
        variable._tk = None


def release_waiting() -> int:
    """Releases the variables freed on other threads; returns how many (main thread only)."""
    count = 0
    while True:
        try:
            interpreter, name, commands = _LATER.get_nowait()
        except queue.Empty:
            return count
        count += 1
        try:
            if interpreter.getboolean(interpreter.call("info", "exists", name)):
                interpreter.globalunsetvar(name)
            for command in commands or ():
                interpreter.deletecommand(command)
        except (tk.TclError, RuntimeError):
            pass  # its interpreter is gone with its window


def install(root: tk.Misc) -> None:
    """Once per Tk interpreter (theme.apply calls it)."""
    tk.Variable.__del__ = _release

    def every() -> None:
        release_waiting()
        try:
            root.after(_EVERY_MS, every)
        except tk.TclError:
            pass
    root.after(_EVERY_MS, every)
