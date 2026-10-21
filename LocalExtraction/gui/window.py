# LocalExtraction/gui/window.py
"""The frame of a window of MoukhlijMatExtract: a title bar with how many PDFs are read at once, one
panel, the log of the engine below it, and what a panel needs from its window — a way for working
threads to touch the widgets, one extraction at a time per folder of results, and the rebuild of a
database of an earlier version. The window of Project 1 (gui/app.py) and that of Project 2
(WebScraping/gui/app.py) are this frame around their own panel."""

import logging
import os
import queue
import threading
import tkinter as tk
from contextlib import contextmanager
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, Iterator

from ..about import CREDIT_TEXT
from ..exporter import StrictExporter
from .widgets import LogPane, Stopped

_TICK_MS = 80          # how often the window looks at what the working threads sent it
_EVENTS_PER_TICK = 300


class _ToWindow(logging.Handler):
    """Sends the log records of the engine — written from working threads — to the window's own
    thread, the only one that may touch a Tkinter widget."""

    def __init__(self, post: Callable[..., None], write: Callable[[str], None]):
        super().__init__()
        self._post, self._write = post, write

    def emit(self, record: logging.LogRecord) -> None:
        self._post(self._write, self.format(record))


class Window:
    """A window around one panel. A subclass gives the panel (`build_panel`) and, if it has any,
    the buttons of its title bar (`header_buttons`)."""

    def __init__(self, root: tk.Tk, title: str, subtitle: str, workers: int = 4,
                 size: str = "1100x820", minsize: tuple = (900, 620)):
        self.root = root
        root.title(title)
        root.geometry(size)
        root.minsize(*minsize)
        self._events: "queue.Queue" = queue.Queue()
        # One extraction at a time writes the files of a folder.
        self._locks: Dict[str, threading.Lock] = {}

        self._build(title, subtitle, workers)
        handler = _ToWindow(self.post, self.log.write)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)
        self._handler = handler

        root.protocol("WM_DELETE_WINDOW", self.close)
        self._closing = False
        self._tick = root.after(_TICK_MS, self._drain)
        self.database_changed()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def build_panel(self, parent: tk.Misc) -> ttk.Frame:
        raise NotImplementedError

    def header_buttons(self, bar: ttk.Frame) -> None:
        """Buttons at the right of the title bar; a window has none unless it says so."""

    def _build(self, title: str, subtitle: str, workers: int) -> None:
        top = ttk.Frame(self.root, padding=(12, 10, 12, 8))
        top.pack(fill="x")
        ttk.Label(top, text=title, font=("TkDefaultFont", 16, "bold")).pack(side="left")
        ttk.Label(top, text=subtitle, foreground="#555555").pack(side="left", padx=12)
        self.header_buttons(top)
        self.workers_var = tk.IntVar(value=workers)
        ttk.Spinbox(top, from_=1, to=32, textvariable=self.workers_var, width=4).pack(side="right", padx=(4, 16))
        ttk.Label(top, text="PDFs read at once:").pack(side="right")

        ttk.Label(self.root, text=CREDIT_TEXT.partition(" — ")[2], foreground="gray",
                  font=("TkDefaultFont", 9)).pack(side="bottom", anchor="e", padx=12, pady=(0, 4))
        outer = ttk.PanedWindow(self.root, orient="vertical")
        outer.pack(fill="both", expand=True, padx=8, pady=(0, 2))
        self.panel = self.build_panel(outer)
        outer.add(self.panel, weight=6)

        # What the engine itself logs: small by default, the divider above it can be dragged.
        self.log = LogPane(outer, height=3)
        outer.add(self.log, weight=0)
        self._outer = outer
        outer.bind("<Map>", self._place_divider)

    def _place_divider(self, event: "tk.Event") -> None:
        self._outer.unbind("<Map>")
        self.root.update_idletasks()
        self._outer.sashpos(0, max(self._outer.winfo_height() - 66, 200))

    # ------------------------------------------------------------------
    # What the panel needs from its window
    # ------------------------------------------------------------------
    def workers(self) -> int:
        try:
            return max(1, int(self.workers_var.get()))
        except (tk.TclError, ValueError):
            return 4

    def post(self, function: Callable[..., Any], *arguments: Any) -> None:
        """Asks the window's thread to call a function: the way a working thread touches a widget."""
        self._events.put((function, arguments))

    def _drain(self) -> None:
        for _ in range(_EVENTS_PER_TICK):
            try:
                function, arguments = self._events.get_nowait()
            except queue.Empty:
                break
            try:
                function(*arguments)
            except tk.TclError:
                pass  # the widget it was for is gone (a dialog that was closed)
            except Exception:
                logging.getLogger(__name__).exception("An update of the window failed")
        if not self._closing:
            self._tick = self.root.after(_TICK_MS, self._drain)

    def _lock(self, folder: str) -> threading.Lock:
        return self._locks.setdefault(os.path.abspath(folder), threading.Lock())

    @contextmanager
    def writing(self, who: str, folder: str, stop_event: threading.Event) -> Iterator[None]:
        """Holds a folder of results for one extraction. Called from a working thread; raises
        Stopped if Stop is pressed while it waits for another extraction into the same folder."""
        lock = self._lock(folder)
        if not lock.acquire(blocking=False):
            logging.info(f"{who}: waiting for the other extraction into {folder} to finish.")
            while not lock.acquire(timeout=0.3):
                if stop_event.is_set():
                    raise Stopped()
        try:
            yield
        finally:
            lock.release()

    def ready_to_extract(self, folder: str) -> bool:
        """Asked when an extraction is about to start: is there a folder for its results, and if it
        holds a database of an earlier version, may it be rebuilt? (Its files are moved aside, not deleted.)"""
        if not folder:
            messagebox.showerror("MoukhlijMatExtract", "Choose a folder for the results first.", parent=self.root)
            return False
        if not StrictExporter.is_outdated(folder):
            return True
        if self._lock(folder).locked():
            messagebox.showinfo("MoukhlijMatExtract", "An extraction is writing this folder: try again when it has finished.",
                                parent=self.root)
            return False
        if not messagebox.askyesno(
                "MoukhlijMatExtract",
                f"The database in “{folder}” was written by an earlier version: its tables have other columns, so "
                "new articles cannot be added to it.\n\nRebuild it now? Its files are moved to a "
                "“previous_<date>” folder inside it — nothing is deleted — and its articles are extracted again "
                "(those whose PDF is no longer there are carried over as they were).",
                parent=self.root):
            return False
        return self._archive(folder)

    def rebuild(self, folder: str) -> None:
        """Moves the database of a folder aside so that its articles are extracted again."""
        if not folder or not os.path.exists(os.path.join(folder, "papers.csv")):
            messagebox.showinfo("MoukhlijMatExtract", "There is no database to rebuild in this folder.", parent=self.root)
            return
        if self._lock(folder).locked():
            messagebox.showinfo("MoukhlijMatExtract", "An extraction is writing this folder: wait for it to finish.",
                                parent=self.root)
            return
        if messagebox.askyesno(
                "MoukhlijMatExtract",
                f"Rebuild the database of “{folder}” from its PDFs? Useful after the program was updated.\n\nThe "
                "present files are moved to a “previous_<date>” folder inside it — nothing is deleted and nothing "
                "is downloaded again; every article comes back, those whose PDF is no longer there as they were. "
                "Then start the extraction.", parent=self.root):
            self._archive(folder)

    def _archive(self, folder: str) -> bool:
        try:
            kept = StrictExporter.archive(folder)
        except OSError as error:
            messagebox.showerror("MoukhlijMatExtract", f"The database could not be moved aside:\n{error}", parent=self.root)
            return False
        if kept:
            logging.info(f"The previous database was moved to {kept}.")
        self.database_changed()
        return True

    def database_changed(self) -> None:
        """Lets the panel show what its folder holds now."""
        self.panel.show_results()

    def close(self) -> None:
        self.panel.stop()
        self.panel.close()
        logging.getLogger().removeHandler(self._handler)
        self._closing = True
        self.root.after_cancel(self._tick)
        self.root.after(150, self.root.destroy)
