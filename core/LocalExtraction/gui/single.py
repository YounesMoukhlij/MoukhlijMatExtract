# LocalExtraction/gui/single.py
"""One copy of each window. A window asked for while it is already open is not opened a second time: the open one
comes to the front (shown again if it was minimised) and a short message says that only one can be open at a time.

    win = single.open_once("about", "About & methods", parent, lambda: make_the_window())

`make` returns the new window (a Toplevel), or None when it did not open one (a question cancelled). The window is
forgotten when it is closed, so the next request opens a new one."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict, Optional

_OPEN: Dict[str, tk.Misc] = {}


def alive(window: Optional[tk.Misc]) -> bool:
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:  # its Tk is gone
        return False


def existing(key: str) -> Optional[tk.Misc]:
    """The open window of this key, or None."""
    window = _OPEN.get(key)
    if alive(window):
        return window
    _OPEN.pop(key, None)
    return None


def register(key: str, window: tk.Misc) -> tk.Misc:
    """Remembers `window` as the one of `key` until it is closed."""
    _OPEN[key] = window

    def closed(event) -> None:
        if event.widget is window and _OPEN.get(key) is window:
            _OPEN.pop(key, None)
    try:
        window.bind("<Destroy>", closed, add="+")
    except tk.TclError:
        pass
    return window


def bring_back(window: tk.Misc, name: str, say: bool = True) -> tk.Misc:
    """The open window in front of the others, and the message that it is already open."""
    try:
        window.deiconify()
        window.lift()
        window.focus_force()
    except tk.TclError:
        return window
    if say:
        from tkinter import messagebox
        messagebox.showinfo("MoukhlijMatExtract", f"{name} is already open.\n\nOnly one can be open at a time — it "
                                                  "has been brought to the front.", parent=window)
    return window


def open_once(key: str, name: str, parent: tk.Misc, make: Callable[[], Optional[tk.Misc]]) -> Optional[tk.Misc]:
    """The window of `key`: the open one brought back (and said), else a new one from `make()`, remembered."""
    window = existing(key)
    if window is not None:
        return bring_back(window, name)
    window = make()
    if window is not None and alive(window):
        register(key, window.winfo_toplevel())
    return window


def once(key: str, name: str, again: Optional[Callable[..., None]] = None):
    """A function that opens a window (`function(parent, …)` returning it), made to open it once: asked again, the
    open one comes back. `again(window, parent, …)` (optional) brings it up to date with what is asked now."""
    import functools

    def wrap(function):
        @functools.wraps(function)
        def opened(parent, *args, **kwargs):
            window = existing(key)
            if window is not None:
                if again is not None:
                    try:
                        again(window, parent, *args, **kwargs)
                    except Exception:  # bringing it up to date never stops it coming back
                        pass
                return bring_back(window, name)
            window = function(parent, *args, **kwargs)
            if window is not None and alive(window):
                register(key, window.winfo_toplevel())
            return window
        return opened
    return wrap
