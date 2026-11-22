# LocalExtraction/gui/theme.py
"""How the buttons of every MoukhlijMatExtract window look and answer the mouse.

  - at rest      a quiet grey button
  - hover        it lights up (blue tint) and the pointer becomes a hand: this is the one you would click
  - pressed      deep blue while the mouse button is down
  - disabled     faded
  - current      the button of the step that is running stays blue until the step ends (and Pause stays
                 blue while paused), so the window always shows which button was pressed
  - next         the button of the step to take next, where a window guides through steps (Evaluate…): blue

Only the buttons change: the native look of every other widget stays. The native macOS button cannot
take a colour, so the buttons are drawn with the "default" theme's elements (which can), whatever theme
the rest uses. The colours follow the system's light or dark appearance when the window opens.

`apply(root)` once per Tk interpreter (every window frame calls it; calling again does nothing);
`mark(button)` / `unmark(button)` for the current step; `suggest(button, yes)` for the next one."""

import tkinter as tk
from tkinter import ttk
from typing import Iterable, Optional

CURRENT = "Current.TButton"
NEXT = "Next.TButton"
_ELEMENT = "Mme.Button.fill"

# (at rest, text, hover, pressed, current, current hovered, disabled, disabled text)
_LIGHT = ("#ffffff", "#1f2328", "#cfe0ff", "#1e40af", "#2563eb", "#1d4ed8", "#e4e6e9", "#a0a6ad")
_DARK = ("#50555d", "#f1f3f4", "#34507a", "#1e40af", "#2563eb", "#3b6fe0", "#383b40", "#8a9097")

# The colours of the windows' design (design.py): a deep navy band, a garnet accent, quiet greys; one set for the
# light appearance and one for the dark.
PALETTES = {
    "light": {"band": "#14325c", "band_text": "#ffffff", "band_muted": "#c3d1e6", "accent": "#1f4e79",
              "garnet": "#8c1d40", "ink": "#1f2328", "muted": "#6b7280", "line": "#d5dbe3", "stripe": "#f2f5f9",
              "chip": "#24477a", "selected": "#d6e4f7", "card": "#ffffff"},
    "dark": {"band": "#0e223f", "band_text": "#ffffff", "band_muted": "#9fb3cf", "accent": "#7fa8e0",
             "garnet": "#d76a8f", "ink": "#eef0f2", "muted": "#9ba3ad", "line": "#3b414a", "stripe": "#262a30",
             "chip": "#1c3a66", "selected": "#2f4a72", "card": "#2a2e35"},
}


def palette(widget: tk.Misc) -> dict:
    """The design colours for the appearance the windows opened in."""
    return PALETTES["dark" if is_dark(widget) else "light"]


def is_dark(root: tk.Misc) -> bool:
    """Is the system in dark mode? (macOS tells Tk; elsewhere the windows are light.)"""
    try:
        return bool(int(root.tk.call("tk::unsupported::MacWindowStyle", "isdark", root.winfo_toplevel())))
    except (tk.TclError, ValueError):
        return False


def apply(root: tk.Misc) -> None:
    style = ttk.Style(root)
    if _ELEMENT in style.element_names():
        return  # this interpreter's buttons are styled already
    from . import tkthreads
    tkthreads.install(root)  # Tk variables freed by a worker thread are released on the main thread
    from .design import app_icon
    app_icon(root)  # the program's icon in the Dock / taskbar, once for this Tk and every window it opens
    for part in ("fill", "padding", "label"):
        style.element_create(f"Mme.Button.{part}", "from", "default")
    style.layout("TButton", [(_ELEMENT, {"sticky": "nswe", "children": [
        ("Mme.Button.padding", {"sticky": "nswe", "children": [("Mme.Button.label", {"sticky": "nswe"})]})]})])
    rest, text, hover, pressed, current, current_hover, disabled, disabled_text = _DARK if is_dark(root) else _LIGHT
    style.configure("TButton", background=rest, foreground=text, padding=(12, 5), anchor="center")
    style.map("TButton",
              background=[("disabled", disabled), ("pressed", pressed), ("active", hover)],
              foreground=[("disabled", disabled_text), ("pressed", "white")])
    style.configure(CURRENT, background=current, foreground="white")
    style.map(CURRENT, background=[("pressed", pressed), ("active", current_hover)],
              foreground=[("disabled", "white"), ("pressed", "white")])
    style.configure(NEXT, background=current, foreground="white")
    style.map(NEXT, background=[("disabled", disabled), ("pressed", pressed), ("active", current_hover)],
              foreground=[("disabled", disabled_text), ("pressed", "white")])
    # The tables, tabs and frames of every window: a little more air, bold headings, the accent colour.
    colours = palette(root)
    style.configure("Treeview", rowheight=25)
    style.configure("Treeview.Heading", font=("TkDefaultFont", 11, "bold"), padding=(6, 4))
    style.map("Treeview", background=[("selected", colours["accent"])], foreground=[("selected", "white")])
    style.configure("TNotebook.Tab", padding=(14, 5))
    style.configure("Sash", sashthickness=8, gripcount=12)  # the lines between areas: easy to catch and drag
    style.configure("TLabelframe.Label", font=("TkDefaultFont", 11, "bold"), foreground=colours["accent"])
    style.configure("Muted.TLabel", foreground=colours["muted"])
    style.configure("Section.TLabel", font=("TkDefaultFont", 13, "bold"), foreground=colours["accent"])
    # A hand over a button that can be pressed (added to the class's own bindings, which do the hover colour).
    root.bind_class("TButton", "<Enter>", _hand, add="+")
    root.bind_class("TButton", "<Leave>", _arrow, add="+")


def _hand(event: tk.Event) -> None:
    try:
        if not event.widget.instate(["disabled"]):
            event.widget.configure(cursor="hand2")
    except (tk.TclError, AttributeError):
        pass


def _arrow(event: tk.Event) -> None:
    try:
        event.widget.configure(cursor="")
    except (tk.TclError, AttributeError):
        pass


def mark(button: Optional[ttk.Button], others: Iterable[ttk.Button] = ()) -> None:
    """`button` is the one whose step runs: it stays blue; `others` go back to normal."""
    for other in others:
        unmark(other)
    if button is not None:
        try:
            button.configure(style=CURRENT)
        except tk.TclError:
            pass


def unmark(button: Optional[ttk.Button]) -> None:
    if button is not None:
        try:
            button.configure(style="TButton")
        except tk.TclError:
            pass


def suggest(button: Optional[ttk.Button], yes: bool = True) -> None:
    """`button` is (or is no longer) the one to press next: blue, like a step under way."""
    if button is not None:
        try:
            button.configure(style=NEXT if yes else "TButton")
        except tk.TclError:
            pass


def label_hover(label: tk.Label, color: "callable") -> None:
    """A coloured label used as a button (the hub's Requirements): lighter under the mouse, darker when
    pressed. `color()` gives its colour at rest (it may change)."""
    def shade(factor: float) -> str:
        r, g, b = (v // 256 for v in label.winfo_rgb(color()))
        mix = (lambda c: int(c + (255 - c) * factor)) if factor > 0 else (lambda c: int(c * (1 + factor)))
        return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, mix(c))) for c in (r, g, b)))
    label.bind("<Enter>", lambda e: label.configure(background=shade(0.22)), add="+")
    label.bind("<Leave>", lambda e: label.configure(background=color()), add="+")
    label.bind("<ButtonPress-1>", lambda e: label.configure(background=shade(-0.25)), add="+")
