# WebScraping/averageScrap/gui/browser_helper.py
"""“Get the rest with my browser…”: the window of the browser helper (browser_helper.py). It opens the pages of the
papers left on the hand list in your own browser, a batch at a time; watches the Downloads folder for their PDFs;
moves each into the by_hand folder and takes it in, with its source recorded. Each paper's line says where it is:
to open, opened, PDF received, taken in."""

import logging
import os
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Sequence

from LocalExtraction.gui import layout
from LocalExtraction.gui.dialogs import Dialog

from .. import by_hand
from ..browser_helper import DownloadsWatcher, default_downloads, next_batch, to_open
from ..ids import normalize_doi
from ..ledger import DOWNLOADED

_LOOK_MS = 2000      # how often the Downloads folder is looked at
_BETWEEN_MS = 700    # between two pages opened, so the browser and the sites are not flooded
_NEXT_MS = 3000      # the pause before the next batch opens by itself
# Papers per batch: a pace that reads like a person reading, well below what makes a publisher block a network.
_BATCH = 5
TO_OPEN, OPENED, RECEIVED, TAKEN, LEFT, SKIPPED = ("to open", "opened", "PDF received", "taken in", "left in by_hand",
                                                    "skipped")
TIP = ("Set your browser to download PDFs automatically (Chrome: Settings → Privacy and security → Site settings → "
       "PDF documents → Download PDFs).")
DONE = frozenset({TAKEN, LEFT, SKIPPED})  # a paper of the batch needs nothing more from the person
_COLOURS = {OPENED: "#1f4e79", RECEIVED: "#d97706", TAKEN: "#2e7d32", LEFT: "#b42318", SKIPPED: "#8c8c8c"}


class BrowserHelperDialog(Dialog):
    """`panel`: the Web scraping panel (its harvest, its steps); `rows`: by_hand.missed_rows."""

    def __init__(self, parent: tk.Misc, panel, rows: Sequence[Dict[str, str]], downloads: Optional[str] = None):
        from LocalExtraction.gui.widgets import Table, WrapLabel
        super().__init__(parent, "Get the remaining papers with your browser", "1000x760")
        layout.minimum(self, 820, 620)
        self.panel = panel
        self.harvest = panel._harvest()
        self.rows = to_open(rows)
        self.by_key = {row["key"]: row for row in self.rows}
        self.key_of = {normalize_doi(row["doi"]): row["key"] for row in self.rows}
        self.state: Dict[str, str] = {row["key"]: TO_OPEN for row in self.rows}
        self.opened: set = set()
        self.current: List[str] = []  # the keys of the batch opened last
        self._next_job: Optional[str] = None
        self.downloads = tk.StringVar(value=downloads or default_downloads())
        self.batch = tk.IntVar(value=_BATCH)
        self.auto_next = tk.BooleanVar(value=True)
        self.status = tk.StringVar()
        self._taking = False
        self._job: Optional[str] = None
        self.watcher = DownloadsWatcher(self.downloads.get(), self.harvest.by_hand_folder, self.key_of)
        grey = "#8c8c8c"

        ttk.Label(self.body, text="Get the remaining papers with your browser", font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        WrapLabel(self.body, foreground=grey, justify="left", text=(
            "These sites refuse programs, but not you. The pages open in your own browser, a few at a time; you save "
            "each PDF; the program does the rest: it moves the PDFs that arrive in your Downloads folder into the "
            "by_hand folder and takes them in — DOI read from the PDF, title checked, source recorded.")).pack(fill="x", pady=(2, 8))
        steps = ttk.LabelFrame(self.body, text="  How  ", padding=(10, 6))
        steps.pack(fill="x")
        for n, text in enumerate((
                "Press “Open the next papers”: their pages open in your browser.",
                "On each page, download the PDF (sign in through your library if the page asks), or press Skip here.",
                "Leave this window open: each PDF is taken in a few seconds after it arrives. When every paper of the "
                "batch is in (or skipped), the next batch opens by itself. Close the browser window of the last batch "
                "when you like (⌘⇧W)."), 1):
            WrapLabel(steps, justify="left", text=f"{n}.  {text}").pack(fill="x", anchor="w", pady=1)
        # The setting that makes it one click per paper: said where it cannot be missed.
        tip = ttk.Frame(self.body)
        tip.pack(fill="x", pady=(8, 0))
        ttk.Label(tip, text="💡", font=("TkDefaultFont", 14)).pack(side="left", anchor="n", padx=(2, 8))
        self.tip = WrapLabel(tip, justify="left", foreground="#d97706", font=("TkDefaultFont", 12, "bold"), text=TIP)
        self.tip.pack(side="left", fill="x", expand=True)

        settings = ttk.Frame(self.body)
        settings.pack(fill="x", pady=(10, 4))
        ttk.Label(settings, text="PDFs arrive in:").pack(side="left")
        ttk.Label(settings, textvariable=self.downloads, font=("TkDefaultFont", 11, "bold")).pack(side="left", padx=(6, 6))
        ttk.Button(settings, text="Change…", command=self._choose_downloads).pack(side="left")
        pace = ttk.Frame(self.body)  # a line of its own: a long folder name never pushes it out of the window
        pace.pack(fill="x", pady=(0, 4))
        ttk.Label(pace, text="Papers per batch:").pack(side="left")
        ttk.Spinbox(pace, from_=1, to=30, width=4, textvariable=self.batch).pack(side="left", padx=(4, 0))
        ttk.Checkbutton(pace, text="open the next batch by itself", variable=self.auto_next,
                        command=self._maybe_next).pack(side="left", padx=(16, 0))

        ttk.Label(self.body, textvariable=self.status, font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(6, 4))

        self.table = Table(self.body, [("state", "State", 120), ("title", "Title", 430), ("journal", "Journal", 170),
                                       ("reason", "Reason", 170)], on_open=self._open_one, stretch="title", height=12)
        for state, colour in _COLOURS.items():
            self.table.tag(state, foreground=colour)
        self.table.fill([self._line(key) for key in self.by_key])

        buttons = ttk.Frame(self.body)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        skipped = len(rows) - len(self.rows)
        note = WrapLabel(self.body, foreground=grey, justify="left", text=(
            "Double-click a paper to open just that one · select papers and press Skip for those you will not get."
            + (f"  {skipped:,} paper(s) are not here: no DOI to match their PDF by, or waiting on a busy site that the "
               "next “3 · Download” tries again." if skipped else "")))
        note.pack(side="bottom", fill="x", anchor="w", pady=(4, 0))
        self.table.pack(fill="both", expand=True)
        self.open_button = ttk.Button(buttons, text="Open the next papers", command=self.open_next)
        self.open_button.pack(side="left")
        ttk.Button(buttons, text="Skip", command=self.skip).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Take in now", command=self.take_in).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Open the by_hand folder", command=self._reveal).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._show_status()
        self._job = self.after(_LOOK_MS, self._look)

    # ------------------------------------------------------------------ the list
    def _line(self, key: str):
        row, state = self.by_key[key], self.state[key]
        return key, (state, row.get("title") or row["doi"], row.get("journal", ""), row.get("reason", "")), \
            ((state,) if state in _COLOURS else ())

    def _set(self, key: str, state: str) -> None:
        if key in self.state and self.state[key] != state:
            self.state[key] = state
            self.table.update_row(self._line(key))

    def _show_status(self) -> None:
        count = {s: 0 for s in (TO_OPEN, OPENED, RECEIVED, TAKEN, LEFT, SKIPPED)}
        for state in self.state.values():
            count[state] += 1
        self.status.set(f"{len(self.rows):,} paper(s) to get · {len(self.opened):,} opened · "
                        f"{count[RECEIVED] + count[TAKEN] + count[LEFT]:,} PDF(s) received · {count[TAKEN]:,} taken in"
                        + (f" · {count[SKIPPED]:,} skipped" if count[SKIPPED] else "")
                        + (f" · {count[LEFT]:,} left in by_hand (see the Activity tab)" if count[LEFT] else ""))

    # ------------------------------------------------------------------ opening pages
    def open_next(self, by_itself: bool = False) -> List[str]:
        """Opens the next batch in the browser, a moment apart. Returns their keys. `by_itself`: opened because the
        last batch was done — no message when nothing is left."""
        self._next_job = None
        try:
            size = int(self.batch.get())
        except (tk.TclError, ValueError):
            size = _BATCH
        batch = next_batch([row for row in self.rows if self.state[row["key"]] == TO_OPEN], self.opened, size)
        if not batch:
            if not by_itself:
                messagebox.showinfo("Browser helper", "Every paper of the list has been opened. Double-click one to "
                                                      "open it again.", parent=self)
            return []
        for index, row in enumerate(batch):
            self.after(index * _BETWEEN_MS, lambda link=row["link"]: webbrowser.open(link))
            self.opened.add(row["key"])
            self._set(row["key"], OPENED)
        self.current = [row["key"] for row in batch]
        self._show_status()
        return list(self.current)

    def batch_done(self) -> bool:
        """Every paper of the batch opened last is in, left in by_hand, or skipped."""
        return bool(self.current) and all(self.state.get(key) in DONE for key in self.current)

    def _maybe_next(self) -> None:
        """The batch is done and “open the next batch by itself” is ticked: the next batch opens after a pause."""
        if self.auto_next.get() and self.batch_done() and self._next_job is None and self.winfo_exists():
            self._next_job = self.after(_NEXT_MS, lambda: self.open_next(by_itself=True))

    def skip(self, keys: Optional[Sequence[str]] = None) -> None:
        """Marks the selected papers (or `keys`) as skipped: they need nothing more, and a batch of them is done."""
        keys = list(keys) if keys is not None else self.table.selected()
        if not keys:
            messagebox.showinfo("Skip", "Select the papers to skip first (click, Shift-click, ⌘/Ctrl-click).", parent=self)
            return
        for key in keys:
            if self.state.get(key) not in (TAKEN, None):
                self._set(key, SKIPPED)
        self._show_status()
        self._maybe_next()

    def _open_one(self, key: str) -> None:
        row = self.by_key.get(key)
        if row:
            webbrowser.open(row["link"])
            self.opened.add(key)
            if self.state[key] == TO_OPEN:
                self._set(key, OPENED)
            self._show_status()

    # ------------------------------------------------------------------ PDFs arriving
    def _look(self) -> None:
        self._job = None
        try:
            for path in self.watcher.scan():
                with open(path, "rb") as f:
                    data = f.read()
                for doi in by_hand.dois_in(data, os.path.basename(path)):
                    if doi in self.key_of and self.state[self.key_of[doi]] != TAKEN:
                        self._set(self.key_of[doi], RECEIVED)
                        break
            if any(state == RECEIVED for state in self.state.values()):
                self.take_in()
            self._show_status()
        except Exception as error:  # a look that fails must not stop the next ones
            logging.warning(f"Browser helper: {error}")
        if self.winfo_exists():
            self._job = self.after(_LOOK_MS, self._look)

    def take_in(self) -> None:
        """Takes in the PDFs of the by_hand folder on a working thread — not while a step of the window runs (the
        step's own download takes them in), nor twice at once."""
        if self._taking or by_hand.waiting(self.harvest.folder) == 0:
            return
        if self.panel.running():
            self.status.set(self.status.get().split("  ·  waiting")[0] + "  ·  waiting for the step under way to end")
            return
        self._taking = True
        harvest, post = self.harvest, self.panel.app.post

        def work() -> None:
            taken = 0
            try:
                harvest.write_hand_list()  # the list take_in matches against: as the ledger stands now
                taken = by_hand.take_in(harvest.folder, harvest.ledger, harvest.hand_list_path)
                harvest.write_hand_list()  # without the papers just taken in
            except Exception as error:
                logging.warning(f"Browser helper: the PDFs could not be taken in ({error}).")
            post(self._taken, taken)
        threading.Thread(target=work, name="mme-browser-take-in", daemon=True).start()

    def _taken(self, taken: int) -> None:
        self._taking = False
        if not self.winfo_exists():
            return
        for key, state in self.state.items():
            if state != RECEIVED:
                continue
            candidate = self.harvest.ledger.get(key)
            self._set(key, TAKEN if candidate is not None and candidate.status == DOWNLOADED else LEFT)
        if taken:
            logging.info(f"Browser helper: {taken} PDF(s) taken in.")
        self._show_status()
        self._maybe_next()

    # ------------------------------------------------------------------ the rest
    def _choose_downloads(self) -> None:
        folder = filedialog.askdirectory(parent=self, initialdir=self.downloads.get(),
                                         title="The folder your browser saves downloads into")
        if folder:
            self.downloads.set(folder)
            self.watcher.watch(folder)  # from now: the PDFs already in that folder are left alone

    def _reveal(self) -> None:
        from LocalExtraction.gui.widgets import open_path
        os.makedirs(self.harvest.by_hand_folder, exist_ok=True)
        open_path(self.harvest.by_hand_folder)

    def close(self) -> None:
        for job in (self._job, self._next_job):
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        self._job = self._next_job = None
        self.destroy()
