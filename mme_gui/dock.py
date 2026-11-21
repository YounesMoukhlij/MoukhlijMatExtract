# mme_gui/dock.py
"""“Add MoukhlijMatExtract to the Dock?”: on macOS, when the main window opens and the program is not in the Dock yet,
a small window offers to put it there, so that it starts with one click.

  - Add to the Dock: makes ~/Applications/MoukhlijMatExtract.app when it is missing (macapp.build), adds it to the
    end of the Dock's apps (the Dock's own settings, com.apple.dock persistent-apps) and restarts the Dock, which
    shows it at once (the Dock blinks, nothing else is touched).
  - Not now: asked again the next time.
  - Don't ask again: remembered (~/.moukhlijmatextract/dock_declined); `mme-gui --install-app` and `make app` still
    make the app, to drag to the Dock by hand.

Elsewhere (Windows, Linux) nothing is offered: there is no Dock."""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from .macapp import DEFAULT as APP, NAME

DECLINED = Path.home() / ".moukhlijmatextract" / "dock_declined"
_DOCK = "com.apple.dock"


def dock_apps() -> list:
    """The apps of the Dock (its persistent-apps), as the Dock keeps them; [] when they cannot be read."""
    try:
        exported = subprocess.run(["defaults", "export", _DOCK, "-"], capture_output=True, timeout=10).stdout
        return list(plistlib.loads(exported).get("persistent-apps", []))
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError):
        return []


def in_dock(apps: Optional[list] = None) -> bool:
    """Whether a MoukhlijMatExtract.app is among the Dock's apps (wherever it is)."""
    for tile in dock_apps() if apps is None else apps:
        url = str(((tile.get("tile-data") or {}).get("file-data") or {}).get("_CFURLString", ""))
        if f"/{NAME}.app" in url:
            return True
    return False


def declined() -> bool:
    try:
        return DECLINED.exists()
    except OSError:
        return False


def decline() -> None:
    try:
        DECLINED.parent.mkdir(parents=True, exist_ok=True)
        DECLINED.touch()
    except OSError:
        pass  # a read-only home: asked again next time, nothing worse


def should_offer(platform: str = sys.platform) -> bool:
    return platform == "darwin" and not declined() and not in_dock()


def tile(app: Path) -> str:
    """The Dock's entry for an app, as `defaults write … -array-add` takes it."""
    url = app.resolve().as_uri().rstrip("/") + "/"
    url = url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return ("<dict><key>tile-data</key><dict><key>file-data</key><dict>"
            f"<key>_CFURLString</key><string>{url}</string><key>_CFURLStringType</key><integer>15</integer>"
            "</dict></dict><key>tile-type</key><string>file-tile</string></dict>")


def add(app: Optional[Path] = None, build: Optional[Callable[[], Path]] = None,
        run: Callable = subprocess.run) -> Path:
    """Makes the app when it is missing, adds it to the Dock (once) and restarts the Dock. Returns the app's path.
    Raises RuntimeError (said to the person) when a step fails."""
    app = Path(app or APP)
    if not app.is_dir():
        if build is None:
            from .macapp import build as build
        app = Path(build())
    if in_dock():
        return app
    done = run(["defaults", "write", _DOCK, "persistent-apps", "-array-add", tile(app)], capture_output=True)
    if getattr(done, "returncode", 0) != 0:
        raise RuntimeError("the Dock's settings could not be changed: drag the app from Applications to the Dock.")
    run(["killall", "Dock"], capture_output=True)  # the Dock starts again at once, with the app in it
    return app


def offer(root, delay_ms: int = 0) -> None:
    """The small window that asks. Waits while another window is open over the main one (a question about the
    main folder, a part), so that two questions never pile up."""
    import tkinter as tk

    def busy() -> bool:
        try:
            return any(isinstance(child, tk.Toplevel) and child.winfo_ismapped() for child in root.winfo_children())
        except tk.TclError:
            return True

    def show() -> None:
        try:
            if not root.winfo_exists():
                return
        except tk.TclError:
            return
        if busy():
            root.after(2000, show)
            return
        _dialog(root)
    root.after(delay_ms, show)


def _dialog(root):
    import tkinter as tk
    from tkinter import messagebox, ttk

    from LocalExtraction.gui import design, layout, theme

    win = tk.Toplevel(root)
    win.title("MoukhlijMatExtract")
    win.resizable(False, False)
    theme.apply(win)
    try:
        win.transient(root)
    except tk.TclError:
        pass
    body = ttk.Frame(win, padding=(22, 18, 22, 16))
    body.pack(fill="both", expand=True)
    top = ttk.Frame(body)
    top.pack(fill="x")
    background = ttk.Style().lookup("TFrame", "background") or theme.palette(win)["card"]
    design.emblem(top, background, size=46).pack(side="left", padx=(0, 14))
    words = ttk.Frame(top)
    words.pack(side="left", fill="x", expand=True)
    ttk.Label(words, text="Add MoukhlijMatExtract to the Dock?", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
    ttk.Label(words, style="Muted.TLabel", wraplength=360, justify="left",
              text="Then it starts with one click, with its own name and icon — no terminal needed. "
                   "You can remove it from the Dock any time (drag it out).").pack(anchor="w", pady=(4, 0))
    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=(16, 0))

    def add_it() -> None:
        win.configure(cursor="watch")
        win.update_idletasks()
        try:
            path = add()
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            win.destroy()
            messagebox.showerror("MoukhlijMatExtract", f"It could not be added to the Dock: {error}", parent=root)
            return
        win.destroy()
        messagebox.showinfo("MoukhlijMatExtract", f"Added: MoukhlijMatExtract is at the end of your Dock.\n\n"
                                                  f"(The app: {path})", parent=root)

    def never() -> None:
        decline()
        win.destroy()

    add_button = ttk.Button(buttons, text="Add to the Dock", command=add_it, style="Next.TButton")
    add_button.pack(side="right")
    ttk.Button(buttons, text="Not now", command=win.destroy).pack(side="right", padx=(0, 8))
    ttk.Button(buttons, text="Don't ask again", command=never).pack(side="left")
    win.bind("<Escape>", lambda event: win.destroy())
    win.bind("<Return>", lambda event: add_it())
    layout.place(win, (520, 190), parent=root)
    add_button.focus_set()
    win.add_it, win.never = add_it, never  # hooks for the tests
    return win
