# LocalExtraction/gui/layout.py
"""Windows that fit the screen they open on, and areas a person resizes by dragging the line between them.

    place(window, size, minsize)   the size asked for, fitted to the screen (a little larger on a large one, never
                                   larger than what the menu bar and the dock or taskbar leave), centred — a dialog
                                   over the window it belongs to
    minimum(window, width, height) a smallest size the screen can hold
    Stack(parent)                  controls above (built in `.host`, scrolling when short), tabs below (`.below`),
                                   a line to drag between them"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Iterable, Optional, Sequence, Tuple, Union

Size = Union[str, Sequence[int]]
_LARGE = (1600, 1000)   # a screen beyond this gets windows up to GROW times larger than asked
GROW = 1.3


def _pair(size: Size) -> Tuple[int, int]:
    if isinstance(size, str):
        width, height = (int(n) for n in size.lower().split("x"))
        return width, height
    return int(size[0]), int(size[1])


def usable(widget: tk.Misc) -> Tuple[int, int]:
    """What a window may take of the screen: the width less a margin, the height less the menu bar and the dock or
    taskbar."""
    return int(widget.winfo_screenwidth() * 0.96), int(widget.winfo_screenheight() * 0.88)


def fitted(widget: tk.Misc, size: Size) -> Tuple[int, int]:
    """The size asked for, for this screen: grown on a large screen, cut to what the screen can show."""
    width, height = _pair(size)
    grow = min(GROW, max(1.0, min(widget.winfo_screenwidth() / _LARGE[0], widget.winfo_screenheight() / _LARGE[1])))
    room_w, room_h = usable(widget)
    return min(int(width * grow), room_w), min(int(height * grow), room_h)


def minimum(window: tk.Misc, width: int, height: int) -> Tuple[int, int]:
    """Sets (and returns) a smallest size the screen can hold."""
    room_w, room_h = usable(window)
    size = min(width, room_w), min(height, room_h)
    window.minsize(*size)
    return size


def place(window: tk.Misc, size: Size, minsize: Optional[Size] = None, parent: Optional[tk.Misc] = None) -> None:
    """Sizes `window` for the screen and centres it: on the screen, or over `parent` (a dialog)."""
    width, height = fitted(window, size)
    if minsize is not None:
        low_w, low_h = minimum(window, *_pair(minsize))
        width, height = max(width, low_w), max(height, low_h)
    screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
    if parent is not None and parent.winfo_ismapped():
        top = parent.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - width) // 2
        y = top.winfo_rooty() + (top.winfo_height() - height) // 3
    else:
        x, y = (screen_w - width) // 2, max((screen_h - height) // 3, 0)
    x = min(max(x, 0), max(screen_w - width, 0))
    y = min(max(y, 0), max(screen_h - height, 0))
    window.geometry(f"{width}x{height}+{x}+{y}")


class Stack:
    """Controls above, tabs below, a line to drag between them. Build the controls inside `host` (they scroll when the
    upper part is shorter than they are), then give the tabs to `below`:

        stack = Stack(panel)
        ttk.Button(stack.host, ...).pack(...)
        stack.below(notebook, cards=[result_card])     # the notebook a child of `panel`

    The upper part is as tall as what it holds while the tabs keep `keep` of the height at least; dragged by hand,
    the line stays where it was put. Cards (built in `host`, shown later) move the line as they are shown and closed."""

    def __init__(self, parent: tk.Misc, keep: float = 0.4):
        from .widgets import Scrolled
        self.keep = keep
        self.split = ttk.PanedWindow(parent, orient="vertical")
        self.split.pack(fill="both", expand=True)
        self.upper = Scrolled(self.split)
        self.split.add(self.upper, weight=0)
        self.host = self.upper.inner
        self._state = {"by_hand": False, "need": -1, "total": -1}

    def below(self, widget: tk.Misc, cards: Iterable = ()) -> None:
        self.split.add(widget, weight=1)
        widget.lift()  # drawn above the line's panes
        self.split.bind("<Configure>", self._resized, add="+")
        self.split.bind("<ButtonRelease-1>", lambda event: self._state.update(by_hand=True), add="+")
        self.host.bind("<Configure>", self._content, add="+")
        for card in cards:
            card._pack = {k: v for k, v in getattr(card, "_pack", {}).items() if k not in ("before", "after", "in_")}
            for sequence in ("<Map>", "<Unmap>"):  # a card shown or closed: the line follows it
                card.bind(sequence, lambda event: self.split.after_idle(self.fit), add="+")

    def fit(self) -> None:
        """The line where it belongs; moved only when that place changed (moving it resizes the panes, which would call
        this again)."""
        try:
            total, need = self.split.winfo_height(), self.host.winfo_reqheight() + 2
            if total <= 1:
                return
            self._state.update(need=need, total=total)
            wanted = max(min(need, int(total * (1 - self.keep))), 40)
            if abs(self.split.sashpos(0) - wanted) > 1:
                self.split.sashpos(0, wanted)
        except tk.TclError:  # the window is closing
            pass

    def _resized(self, event) -> None:  # the window resized: the line follows, unless it was dragged
        if not self._state["by_hand"] and event.widget is self.split and \
                self.split.winfo_height() != self._state["total"]:
            self.fit()

    def _content(self, event) -> None:  # what the upper part holds grew or shrank (a line wrapped, a notice shown)
        if not self._state["by_hand"] and self.host.winfo_reqheight() + 2 != self._state["need"]:
            self.split.after_idle(self.fit)
