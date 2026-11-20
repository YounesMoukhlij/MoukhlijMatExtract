# LocalExtraction/gui/window.py
"""The frame of a window of MoukhlijMatExtract: a title bar with how many PDFs are read at once, one
panel, the log of the engine below it, and what a panel needs from its window — a way for working
threads to touch the widgets, one extraction at a time per folder of results, and the rebuild of a
database of an earlier version. The window of Project 1 (gui/app.py) and that of Project 2
(WebScraping/gui/app.py) are this frame around their own panel."""

import csv
import logging
import os
import queue
import threading
import time
import tkinter as tk
from contextlib import contextmanager
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, Iterator, Optional

from .. import runcontrol
from ..exporter import StrictExporter, UnreadableTable
from . import design, dialogs, theme
from .widgets import LogPane, Stopped

_TICK_MS = 80          # how often the window looks at what the working threads sent it
_EVENTS_PER_TICK = 300
_DRAIN_SECONDS = 0.04  # the time the window gives to those messages at each tick


class _ToWindow(logging.Handler):
    """Sends the log records of the engine — written from working threads — to the window's own
    thread, the only one that may touch a Tkinter widget. `busy()` says whether a step of the window runs:
    its lines then go to the Activity tab too (decided when the line is written, not when it is shown)."""

    def __init__(self, post: Callable[..., None], write: Callable[[str, str, bool], None],
                 busy: Callable[[], bool] = lambda: False):
        super().__init__()
        self._post, self._write, self._busy = post, write, busy

    def emit(self, record: logging.LogRecord) -> None:
        try:
            busy = bool(self._busy())
        except Exception:
            busy = False
        message = record.getMessage()
        if record.levelno >= logging.WARNING:
            message = f"{record.levelname}: {message}"
        self._post(self._write, self.format(record), message, busy)


def fit_to_screen(root: tk.Misc, size):
    """A window size ("1100x820" or (900, 620)) made to fit the screen: never wider than 95 % of it,
    nor higher than 88 % (room for the menu bar, the dock or the taskbar)."""
    if isinstance(size, str):
        width, height = (int(n) for n in size.lower().split("x"))
    else:
        width, height = size
    width = min(width, int(root.winfo_screenwidth() * 0.95))
    height = min(height, int(root.winfo_screenheight() * 0.88))
    return f"{width}x{height}" if isinstance(size, str) else (width, height)


class Window:
    """A window around one panel. A subclass gives the panel (`build_panel`) and, if it has any,
    the buttons of its title bar (`header_buttons`)."""

    def __init__(self, root: tk.Tk, title: str, subtitle: str, workers: int = 4,
                 size: str = "1100x820", minsize: tuple = (900, 620)):
        self.root = root
        theme.apply(root)  # buttons that light up under the mouse and show the step that runs
        root.title(title)
        from . import layout
        layout.place(root, size, minsize)  # fitted to the screen it opens on, centred
        self._events: "queue.Queue" = queue.Queue()
        # One extraction at a time writes the files of a folder.
        self._locks: Dict[str, threading.Lock] = {}

        self._build(title, subtitle, workers)
        handler = _ToWindow(self.post, self._logged, self._step_running)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)
        self._handler = handler

        # The web requests that wait for the internet say so in the panel's status line.
        self._connection = lambda online: self.post(self._connection_changed, online)
        runcontrol.on_connection(self._connection)

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
        # The band: the program, the window's title, what it does, the version.
        kicker, _, part = title.rpartition(" · ")
        self.band = design.header(self.root, part or title, subtitle, kicker=kicker or design.KICKER, compact=True)
        top = ttk.Frame(self.root, padding=(12, 8, 12, 6))
        top.pack(fill="x")
        self.header_buttons(top)
        self.workers_var = tk.IntVar(value=workers)
        ttk.Spinbox(top, from_=1, to=32, textvariable=self.workers_var, width=4).pack(side="right", padx=(4, 16))
        ttk.Label(top, text="PDFs read at once:").pack(side="right")
        ttk.Button(top, text="About & methods", command=self.about).pack(side="left")

        design.footer(self.root, about=self.about).pack(side="bottom", fill="x")
        outer = ttk.PanedWindow(self.root, orient="vertical")
        outer.pack(fill="both", expand=True, padx=8, pady=(0, 2))
        self.panel = self.build_panel(outer)
        outer.add(self.panel, weight=6)
        # Ctrl-C in the terminal stops this window's step as Stop does, before the window closes (crashlog).
        self._forget_step = runcontrol.register_step(self.panel.running, self.panel.stop)
        # “‹ Back” (design.header): asks first while a step runs, then closes as the close button does.
        self.root._mme_busy, self.root._mme_close = self.panel.running, self.close

        # What the engine itself logs: small by default, the divider above it can be dragged.
        self.log = LogPane(outer, height=3)
        outer.add(self.log, weight=0)
        self._outer = outer
        outer.bind("<Map>", self._place_divider)

    def _step_running(self) -> bool:
        running = getattr(self.panel, "running", None)
        return bool(running()) if running is not None else False

    def _logged(self, line: str, message: str, busy: bool) -> None:
        """A line of the engine: in the log strip, and — written while a step ran — in the panel's Activity tab, so
        that the tab holds everything the step did (Fetch DOIs, the search, the download, the extraction)."""
        self.log.write(line)
        activity = getattr(self.panel, "activity", None)
        if busy and activity is not None:
            activity.write(message)

    def about(self) -> None:
        """The “About & methods” window: the software, how to cite it, the method, the rules on sources, the
        accuracy measured here and the environment."""
        from .about_window import open_about
        open_about(self.root)

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
        # As many as fit in _DRAIN_SECONDS (at least _EVENTS_PER_TICK): a step that sent thousands of
        # messages is caught up with in moments, and the window still answers the mouse between ticks.
        start = time.monotonic()
        handled = 0
        while handled < _EVENTS_PER_TICK or time.monotonic() - start < _DRAIN_SECONDS:
            handled += 1
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

    def ready_to_extract(self, folder: str, new_pdfs: Optional[int] = None) -> bool:
        """Asked when an extraction is about to start: is there a folder for its results, and what becomes of
        the data already in it — the new articles added to it, or a new database (the present one moved
        into "previous_<date>", nothing deleted)? `new_pdfs`: how many PDFs are about to be read; given, the
        question is asked whenever the folder holds data and there is something new to add; None, only
        when that data was written by an earlier version (the web part: its database grows run by run)."""
        if not folder:
            messagebox.showerror("MoukhlijMatExtract", "Choose a folder for the results first.", parent=self.root)
            return False
        articles = self._articles_in(folder)
        if not articles:
            return True
        outdated = StrictExporter.is_outdated(folder)
        if not outdated and not new_pdfs:
            return True
        if self._lock(folder).locked():
            messagebox.showinfo("MoukhlijMatExtract", "An extraction is writing this folder: try again when it has finished.",
                                parent=self.root)
            return False
        can_add = not outdated or StrictExporter.can_upgrade(folder)
        about = (f"“{folder}” already holds the data of {articles:,} article{'s' if articles != 1 else ''}"
                 + (", written by an earlier version of the program" if outdated else "") + "."
                 + (f" {new_pdfs:,} new PDF{'s are' if new_pdfs != 1 else ' is'} about to be extracted." if new_pdfs else "")
                 + "\n\nWhat should happen to the data already there?")
        add = ("add", "Add the new articles to it",
               "Keep it as it is and add the new articles to it."
               + (" Its tables are brought up to date first — the columns this version added (moving ion, "
                  "plausibility, …) are worked out for its rows, nothing is extracted again — and a copy of them "
                  "as they were is kept in “previous_<date>”." if outdated else ""))
        fresh = ("new", "Start a new database",
                 "Move it into a “previous_<date>” folder inside — nothing is deleted — and build a new database: "
                 "every PDF is extracted again by this version (articles whose PDF is no longer there are carried "
                 "over as they were).")
        if not can_add:
            about += ("\n\nIts tables are too different from this version's for new articles to be added to "
                      "them: only a new database is possible.")
        answer = dialogs.ask_choice(self.root, "There is already data here", about,
                                    [add, fresh] if can_add else [fresh])
        if answer == "new":
            return self._archive(folder)
        if answer == "add":
            if not outdated:
                return True
            try:
                kept = StrictExporter.upgrade(folder)
            except (OSError, ValueError, UnreadableTable) as error:
                messagebox.showerror("MoukhlijMatExtract", f"The database could not be brought up to date:\n{error}\n\n"
                                     "Choose “Start a new database” instead.", parent=self.root)
                return False
            logging.info(f"The database was brought up to date; its files as they were are in {kept}.")
            self.database_changed()
            return True
        return False

    @staticmethod
    def _articles_in(folder: str) -> int:
        """How many articles the database of a folder holds (0 when there is none)."""
        path = os.path.join(folder, "papers.csv")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return 0
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                return max(0, sum(1 for _ in csv.reader(f)) - 1)
        except (OSError, csv.Error, UnicodeDecodeError):
            return 1  # there is something: the question is asked

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

    def _connection_changed(self, online: bool) -> None:
        changed = getattr(self.panel, "connection_changed", None)
        if changed is not None:
            changed(online)

    def close(self) -> None:
        self._forget_step()
        runcontrol.off_connection(self._connection)
        self.panel.stop()
        self.panel.close()
        logging.getLogger().removeHandler(self._handler)
        self._closing = True
        self.root.after_cancel(self._tick)
        self.root.after(150, self.root.destroy)
