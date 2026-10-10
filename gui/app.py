# gui/app.py
"""The main window: the two panels side by side, each with its own folder of results, and what
they share — how many PDFs are read at once, the settings, the log of the engine."""

import logging
import os
import queue
import threading
import tkinter as tk
from contextlib import contextmanager
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, Iterator, Optional

from exporter import StrictExporter
from gui.dialogs import SettingsDialog
from gui.local_panel import LocalPanel
from gui.web_panel import WebPanel
from gui.widgets import LogPane, Stopped
from main import _CREDIT_TEXT, LOCAL_OUTPUT, WEB_OUTPUT

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


class App:
    def __init__(self, root: tk.Tk, local_output: str = LOCAL_OUTPUT, web_output: str = WEB_OUTPUT,
                 input_dir: str = "papers", job_path: str = "", workers: int = 4):
        self.root = root
        root.title("AutoMatExtract")
        root.geometry("1440x860")
        root.minsize(1180, 680)
        self._events: "queue.Queue" = queue.Queue()
        # One extraction at a time writes the files of a folder. The two sides have a folder each,
        # so they do not wait for one another — unless both are pointed at the same one.
        self._locks: Dict[str, threading.Lock] = {}

        self._build(local_output, web_output, input_dir, job_path, workers)
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
    def _build(self, local_output: str, web_output: str, input_dir: str, job_path: str, workers: int) -> None:
        top = ttk.Frame(self.root, padding=(12, 10, 12, 8))
        top.pack(fill="x")
        ttk.Label(top, text="AutoMatExtract", font=("TkDefaultFont", 16, "bold")).pack(side="left")
        ttk.Label(top, text="articles on this computer and articles from the web, each into its own folder of results",
                  foreground="#555555").pack(side="left", padx=12)
        ttk.Button(top, text="Settings…", command=self._settings).pack(side="right")
        self.workers_var = tk.IntVar(value=workers)
        ttk.Spinbox(top, from_=1, to=32, textvariable=self.workers_var, width=4).pack(side="right", padx=(4, 16))
        ttk.Label(top, text="PDFs read at once:").pack(side="right")

        ttk.Label(self.root, text=_CREDIT_TEXT.partition(" — ")[2], foreground="gray",
                  font=("TkDefaultFont", 9)).pack(side="bottom", anchor="e", padx=12, pady=(0, 4))
        outer = ttk.PanedWindow(self.root, orient="vertical")
        outer.pack(fill="both", expand=True, padx=8, pady=(0, 2))
        sides = ttk.PanedWindow(outer, orient="horizontal")
        self.local = LocalPanel(sides, self, input_dir, local_output)
        self.web = WebPanel(sides, self, job_path, web_output)
        sides.add(self.local, weight=2)
        sides.add(self.web, weight=3)
        outer.add(sides, weight=6)
        # The web side has more to show: it gets the larger share once the window knows its width.
        self._sides = sides
        sides.bind("<Map>", self._place_divider)

        # What the engine itself logs, for both sides: small by default, the divider above it can be dragged.
        self.log = LogPane(outer, height=3)
        outer.add(self.log, weight=0)
        self._outer = outer

    def _place_divider(self, event: "tk.Event") -> None:
        self._sides.unbind("<Map>")
        self.root.update_idletasks()
        self._sides.sashpos(0, int(self._sides.winfo_width() * 0.42))
        self._outer.sashpos(0, max(self._outer.winfo_height() - 66, 200))

    # ------------------------------------------------------------------
    # What the panels share
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
            messagebox.showerror("AutoMatExtract", "Choose a folder for the results first.", parent=self.root)
            return False
        if not StrictExporter.is_outdated(folder):
            return True
        if self._lock(folder).locked():
            messagebox.showinfo("AutoMatExtract", "An extraction is writing this folder: try again when it has finished.",
                                parent=self.root)
            return False
        if not messagebox.askyesno(
                "AutoMatExtract",
                f"The database in “{folder}” was written by an earlier version: its tables have other columns, so "
                "new articles cannot be added to it.\n\nRebuild it now? Its files are moved to a "
                "“previous_<date>” folder inside it — nothing is deleted — and its articles are extracted again.",
                parent=self.root):
            return False
        return self._archive(folder)

    def rebuild(self, folder: str) -> None:
        """Moves the database of a folder aside so that its articles are extracted again."""
        if not folder or not os.path.exists(os.path.join(folder, "papers.csv")):
            messagebox.showinfo("AutoMatExtract", "There is no database to rebuild in this folder.", parent=self.root)
            return
        if self._lock(folder).locked():
            messagebox.showinfo("AutoMatExtract", "An extraction is writing this folder: wait for it to finish.",
                                parent=self.root)
            return
        if messagebox.askyesno(
                "AutoMatExtract",
                f"Rebuild the database of “{folder}” from its PDFs? Useful after the program was updated.\n\nThe "
                "present files are moved to a “previous_<date>” folder inside it — nothing is deleted and nothing "
                "is downloaded again. Then start the extraction on that side.", parent=self.root):
            self._archive(folder)

    def _archive(self, folder: str) -> bool:
        try:
            kept = StrictExporter.archive(folder)
        except OSError as error:
            messagebox.showerror("AutoMatExtract", f"The database could not be moved aside:\n{error}", parent=self.root)
            return False
        if kept:
            logging.info(f"The previous database was moved to {kept}.")
        self.database_changed()
        return True

    def database_changed(self) -> None:
        """Lets each side show what its folder holds now."""
        self.local.show_results()
        self.web.show_results()

    def _settings(self) -> None:
        SettingsDialog(self.root, on_saved=self.web.settings_changed)

    def close(self) -> None:
        self.local.stop()
        self.web.stop()
        self.web.close()
        logging.getLogger().removeHandler(self._handler)
        self._closing = True
        self.root.after_cancel(self._tick)
        self.root.after(150, self.root.destroy)


def main(local_output: str = LOCAL_OUTPUT, web_output: str = WEB_OUTPUT, input_dir: str = "papers",
         job_path: Optional[str] = None, workers: int = 4) -> None:
    from web.job import load_env
    load_env()  # the keys and the contact address of the web side, from the .env file
    if job_path is None:
        default = os.path.join("configs", "sse.yaml")
        job_path = default if os.path.exists(default) else ""
    root = tk.Tk()
    App(root, local_output, web_output, input_dir, job_path, workers)
    root.mainloop()
