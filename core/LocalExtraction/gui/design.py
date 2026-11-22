# LocalExtraction/gui/design.py
"""The look every window of MoukhlijMatExtract shares: a header band (the emblem, the program's name, the window's
title and what it does, the version), a thin garnet rule under it, and a footer that says what the program
commits to. The colours are theme.palette's, for the light or the dark appearance.

    header(root, "Web scraping", "search the literature, download the legal copies, extract them")
    footer(root)          # packed at the bottom before the window's body
    website_line(window)  # the website's address at the bottom of a smaller window (a dialog, a table, a guide)
    stripes(treeview)     # every other row of a table shaded"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from . import theme

# The program's icon (scripts/make_icon.py draws it): the emblem below on the navy of the header band.
ICON = Path(__file__).resolve().parent / "assets" / "mme_icon.png"

KICKER = "MoukhlijMatExtract (MME)"
# What the program commits to, in the footer of every window: each claim is what the code does (legal sources
# only, the sentence and page of each value, a record of each run).
PROMISE = "legal sources only · each value traced to its sentence and page · each run recorded"


def app_icon(root: tk.Misc) -> None:
    """The program's icon for every window of this Tk: in the Dock (macOS), the taskbar (Windows) and the title bar
    (Linux), in place of Tk's blank one. Without its file, the windows keep Tk's own icon."""
    try:
        large = tk.PhotoImage(master=root, file=str(ICON))
        small = tk.PhotoImage(master=root)
        small.tk.call(small, "copy", large, "-subsample", 8, 8)  # 64 × 64: a title bar, a taskbar
        root.winfo_toplevel().iconphoto(True, large, small)
        root.winfo_toplevel()._mme_icon = (large, small)  # kept: an image Python lets go of is gone from the Dock
    except (tk.TclError, OSError):
        pass
    from .appname import set_app_name
    set_app_name()  # “MoukhlijMatExtract” in the Dock, the app switcher and the menu bar of macOS, not “python”


def emblem(parent: tk.Misc, background: str, size: int = 42) -> tk.Canvas:
    """A small crystal: a unit cell drawn in perspective, its atoms on the corners and one in the middle."""
    colours = theme.palette(parent)
    canvas = tk.Canvas(parent, width=size, height=size, background=background, highlightthickness=0, borderwidth=0)
    s = size / 42
    front = [(6, 14), (26, 14), (26, 34), (6, 34)]
    back = [(16, 6), (36, 6), (36, 26), (16, 26)]
    scaled = lambda points: [(x * s, y * s) for x, y in points]  # noqa: E731
    front, back = scaled(front), scaled(back)
    line = colours["band_muted"]
    for a, b in zip(back, back[1:] + back[:1]):
        canvas.create_line(*a, *b, fill=line, width=1)
    for a, b in zip(front, back):
        canvas.create_line(*a, *b, fill=line, width=1)
    for a, b in zip(front, front[1:] + front[:1]):
        canvas.create_line(*a, *b, fill="white", width=1.5)
    r = 2.6 * s
    for x, y in back + front:
        canvas.create_oval(x - r, y - r, x + r, y + r, fill=colours["band_muted"], outline="")
    cx, cy = 21 * s, 20 * s
    canvas.create_oval(cx - 4 * s, cy - 4 * s, cx + 4 * s, cy + 4 * s, fill=colours["garnet"], outline="white")
    return canvas


# ---------------------------------------------------------------------------------------------------------------------
# Back: every window opened from another one has a way back to it, besides the title bar's close button
# ---------------------------------------------------------------------------------------------------------------------
BACK_TO_MAIN = "‹  Back to the main window"
BACK = "‹  Back"
BACK_KEY = "<Command-bracketleft>" if sys.platform == "darwin" else "<Alt-Left>"  # the usual “go back” shortcut


def opener_of(window: tk.Misc) -> Optional[tk.Misc]:
    """The window a window was opened from (None for a window of its own, started alone)."""
    window = window.winfo_toplevel()
    if not isinstance(window, tk.Toplevel) or window.master is None:
        return None
    return window.master.winfo_toplevel()


def back_text(window: tk.Misc) -> str:
    opener = opener_of(window)
    return BACK_TO_MAIN if opener is not None and getattr(opener, "_mme_hub", False) else BACK


def go_back(window: tk.Misc) -> bool:
    """Closes a window and brings back the one it was opened from. A window whose step is still running
    (`window._mme_busy()`) asks first: going back stops the step, keeping what it finished. The window closes by its
    own `window._mme_close` when it has one (it stops its step and lets go of its files), else it is destroyed.
    A window whose work cannot be stopped half-way (`window._mme_finish_first`: a classification, a ranking — seconds,
    their files written in one go) asks nothing: it says it goes back when the work is done, then does.
    Returns whether it went back now."""
    window = window.winfo_toplevel()
    busy = getattr(window, "_mme_busy", None)

    def running() -> bool:
        try:
            return bool(busy and busy())
        except Exception:
            return False
    if running() and getattr(window, "_mme_finish_first", False):
        if getattr(window, "_mme_going_back", False):
            return False  # already waiting to go back
        window._mme_going_back = True
        pill = getattr(window, "_mme_back_pill", None)
        if pill is not None:
            pill.configure(text="‹  Going back when it's done …", cursor="watch")

        def when_done() -> None:
            try:
                if not window.winfo_exists():
                    return
                if running():
                    window.after(150, when_done)
                    return
            except tk.TclError:
                return
            window._mme_going_back = False
            go_back(window)
        when_done()
        return False
    if running():
        from tkinter import messagebox
        if not messagebox.askyesno(
                "Go back?", "A step is still running in this window.\n\nGoing back stops it. Everything it has "
                "finished is saved, and the next run goes on from there.\n\nStop it and go back?",
                icon="warning", parent=window):
            return False
    opener = opener_of(window)
    close = getattr(window, "_mme_close", None) or window.destroy
    close()
    if opener is not None:
        try:
            opener.deiconify()
            opener.lift()
            opener.focus_force()
        except tk.TclError:
            pass
    return True


def back_button(parent: tk.Misc, window: Optional[tk.Misc] = None):
    """A “‹ Back” button for the bottom bar of a window without a header band (it replaces “Close”). Not packed."""
    from tkinter import ttk
    window = (window or parent).winfo_toplevel()
    button = ttk.Button(parent, text=back_text(window), command=lambda: go_back(window))
    window.bind(BACK_KEY, lambda event: go_back(window))
    button.back = True  # for the tests
    return button


def _back_pill(band: tk.Frame, window: tk.Misc, colours: dict, compact: bool) -> tk.Label:
    """The back button of a header band: a quiet chip that lights up under the pointer, at the band's left."""
    rest, lit = colours["chip"], colours["garnet"]
    pill = tk.Label(band, text=back_text(window), background=rest, foreground=colours["band_text"], cursor="hand2",
                    font=("TkDefaultFont", 11 if compact else 12, "bold"), padx=12, pady=3 if compact else 6,
                    takefocus=1)
    pill.bind("<Enter>", lambda event: pill.configure(background=lit))
    pill.bind("<Leave>", lambda event: pill.configure(background=rest))
    for sequence in ("<Button-1>", "<Return>", "<space>"):
        pill.bind(sequence, lambda event: go_back(window))
    window.bind(BACK_KEY, lambda event: go_back(window))
    pill.back = True  # for the tests
    window._mme_back_pill = pill  # its words change while it waits for work that cannot be stopped
    return pill


def header(parent: tk.Misc, title: str, subtitle: str = "", kicker: str = KICKER,
           version: Optional[str] = None, compact: bool = False, back: bool = True, flow: bool = True) -> tk.Frame:
    """The band at the top of a window. Packed here (top, full width); returns the band. `version` None: the
    installed version. `compact`: one line, for a window whose tables need the height. `back`: a window opened from
    another one gets “‹ Back” at the band's left (“‹ Back to the main window” when opened from it). `flow`: the
    floating “⇄ Flow” button at the window's bottom right, which opens the process flow from scratch."""
    colours = theme.palette(parent)
    if version is None:
        from ..about import version as installed
        version = installed()
    band = tk.Frame(parent, background=colours["band"], padx=14 if compact else 16, pady=5 if compact else 10)
    band.pack(side="top", fill="x")
    if back and opener_of(parent) is not None:
        band.back = _back_pill(band, parent.winfo_toplevel(), colours, compact)
        band.back.pack(side="left", padx=(0, 14 if compact else 16))
    emblem(band, colours["band"], size=30 if compact else 42).pack(side="left", padx=(0, 12 if compact else 14))
    texts = tk.Frame(band, background=colours["band"])
    texts.pack(side="left", fill="x", expand=True)
    if kicker and not compact:
        tk.Label(texts, text=kicker.upper(), background=colours["band"], foreground=colours["band_muted"],
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
    title_label = tk.Label(texts, text=title, background=colours["band"], foreground=colours["band_text"],
                           font=("TkDefaultFont", 15 if compact else 18, "bold"))
    title_label.pack(side="left" if compact else "top", anchor="w")
    if subtitle:
        tk.Label(texts, text=subtitle, background=colours["band"], foreground=colours["band_muted"],
                 font=("TkDefaultFont", 11), justify="left", anchor="w").pack(
            side="left" if compact else "top", anchor="w", fill="x", padx=(12, 0) if compact else 0)
    if version:
        tk.Label(band, text=f"v{version}", background=colours["chip"], foreground=colours["band_text"],
                 font=("TkDefaultFont", 10, "bold"), padx=8, pady=2).pack(side="right", anchor="n")
    tk.Frame(parent, background=colours["garnet"], height=3).pack(side="top", fill="x")
    band.title_text = title  # what the tests and the hub read back
    if flow:
        try:
            from mme_gui.process_flow import add_flow_button
            band.flow = add_flow_button(parent.winfo_toplevel(), title)
        except Exception:  # a button is never worth a window that does not open
            band.flow = None
    return band


def footer(parent: tk.Misc, about: Optional[Callable[[], None]] = None) -> tk.Frame:
    """The line at the bottom of a window: the version and licence, what the program commits to, who made it, and
    “About & methods” when given. Pack it (side bottom) before the window's body, so that it keeps its room."""
    from ..about import AUTHOR, LICENSE_NAME, version
    colours = theme.palette(parent)
    bar = tk.Frame(parent)
    tk.Frame(bar, background=colours["line"], height=1).pack(side="top", fill="x")
    line = tk.Frame(bar, padx=12, pady=4)
    line.pack(fill="x")
    # The right-hand items first: when the window narrows, the sentence is what gets cut.
    if about is not None:
        link = tk.Label(line, text="About & methods", foreground=colours["accent"], cursor="hand2",
                        font=("TkDefaultFont", 9, "underline"))
        link.pack(side="right")
        link.bind("<Button-1>", lambda event: about())
    website_link(line).pack(side="right", padx=(0, 12))
    tk.Label(line, text=f"Created by {AUTHOR}", foreground=colours["muted"],
             font=("TkDefaultFont", 9)).pack(side="right", padx=(0, 12))
    keep_awake_switch(line).pack(side="right", padx=(0, 16))
    number = version()
    text = f"MoukhlijMatExtract{f' v{number}' if number else ''} · {LICENSE_NAME} · {PROMISE}"
    tk.Label(line, text=text, foreground=colours["muted"], font=("TkDefaultFont", 9), anchor="w").pack(
        side="left", fill="x", expand=True)
    return bar


KEEP_AWAKE_TEXT = "☕ Keep the computer awake"


def keep_awake_switch(parent: tk.Misc):
    """The “Keep the computer awake” switch (keep_awake.py): one state for the whole program, so ticking it in any
    window ticks it in every other. Not packed. Disabled, with a hint, where this computer offers no way."""
    from tkinter import ttk
    from ..keep_awake import AWAKE
    var = tk.BooleanVar(master=parent, value=AWAKE.on)
    switch = ttk.Checkbutton(parent, text=KEEP_AWAKE_TEXT, variable=var, command=lambda: var.set(AWAKE.set(var.get())))
    if not AWAKE.supported():
        switch.state(["disabled"])

    def follow(on: bool) -> None:  # another window's switch changed it
        if switch.winfo_exists() and var.get() != on:
            var.set(on)
    forget = AWAKE.listen(follow)
    switch.bind("<Destroy>", lambda event: forget() if event.widget is switch else None, add="+")
    switch.var = var  # for the tests
    return switch


def website_address() -> str:
    """The website as people read it: its address without https://."""
    from ..about import WEBSITE
    return WEBSITE.split("://", 1)[-1].rstrip("/")


def open_website() -> None:
    """The website in the default browser."""
    import webbrowser
    from ..about import WEBSITE
    webbrowser.open(WEBSITE)


def website_link(parent: tk.Misc, size: int = 9, background: Optional[str] = None) -> tk.Label:
    """The website's address as a link: a click opens it in the browser. Not packed."""
    colours = theme.palette(parent)
    options = {"background": background} if background else {}
    link = tk.Label(parent, text=f"Website: {website_address()} ↗", foreground=colours["accent"], cursor="hand2",
                    font=("TkDefaultFont", size, "underline"), **options)
    link.bind("<Button-1>", lambda event: open_website())
    link.website = True  # what the tests look for
    return link


def website_line(window: tk.Misc) -> tk.Frame:
    """The website's address at the bottom of a window that has no footer of its own (a dialog, a table of results,
    a guide). Packed at the bottom, before what the window holds already, so that it keeps its room however small
    the window is made. A window whose content is laid out with grid keeps it as it is (Tk mixes no two)."""
    colours = theme.palette(window)
    bar = tk.Frame(window)
    tk.Frame(bar, background=colours["line"], height=1).pack(side="top", fill="x")
    line = tk.Frame(bar, padx=12, pady=3)
    line.pack(fill="x")
    tk.Label(line, text="How to use it, and an overview of the project:", foreground=colours["muted"],
             font=("TkDefaultFont", 9)).pack(side="left")
    website_link(line).pack(side="left", padx=(4, 0))
    if window.grid_slaves():
        bar.destroy()
        return bar
    packed = window.pack_slaves()
    bar.pack(side="bottom", fill="x", **({"before": packed[0]} if packed else {}))
    return bar


def stripes(tree, tag: str = "stripe") -> None:
    """Every other row of a table shaded (the rows given `tag`)."""
    tree.tag_configure(tag, background=theme.palette(tree)["stripe"])
