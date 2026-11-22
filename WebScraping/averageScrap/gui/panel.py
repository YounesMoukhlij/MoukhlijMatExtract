# WebScraping/gui/panel.py
"""The articles from the web. The steps of `python -m WebScraping` as buttons — search, (review in
the table,) download, extract — run by the same WebScraping.harvest.Harvest, on the same ledger and
review list, so a run started in the terminal goes on here and the other way round."""

import logging
import os
import re
import threading
import time
from collections import Counter
import tkinter as tk
import webbrowser
from tkinter import messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from LocalExtraction import outputs, runcontrol
from LocalExtraction.outputs import Group
from LocalExtraction.gui.delete_outputs import delete_outputs_button
from LocalExtraction.gui.dialogs import DetailsDialog
from LocalExtraction.gui.outcomes import extraction_outcome, snapshot
from LocalExtraction.gui.result_card import BAD, FAILED as CARD_FAILED, GOOD, GREY, NOTHING, WARNING, Outcome as Card, ResultCard, Stat, number
from LocalExtraction.gui.results import EnergiesView, pending_pdfs
from LocalExtraction.gui.summary import final_summary, summarize_paper
from LocalExtraction.gui import theme
from LocalExtraction.gui.progress import Tracker, details_button, show_stop_note, stop_note, style_running
from LocalExtraction.gui.progress_text import Pace
from LocalExtraction.gui.widgets import FolderRow, LogPane, Pausable, Row, Stopped, Table, WrapLabel, open_path
from LocalExtraction.models import PaperData

from ..about import DEFAULT_OUTPUT, output_for
from ..fetch import HAND_LIST, Outcome
from ..harvest import MAX_ATTEMPTS, SEARCH_STEPS, Harvest
from ..job import Job, load_job
from ..resolve import REFUSED_EMAIL, email_advice
from ..ledger import APPROVED, CLOSED, DOWNLOADED, EXTRACTED, FAILED, NO, REJECTED, SCREENED, YES, Candidate, abstract_basis
from .. import by_hand
from .dialogs import CheckDialog, MissedDialog
from .job_dialog import JobDialog, open_job_settings, when_saved

WARNING_COLOUR = "#d97706"  # the tile of the papers to get by hand

if TYPE_CHECKING:
    from LocalExtraction.gui.window import Window

_QUIET, _NOW, _DONE = "#8c8c8c", "#0a66c2", "#1a7f37"  # a step to come, under way, done
_EMPTY = "#b3261e"  # no DOI saved yet
# The steps "2 · Search" shows: Fetch DOIs is its own button, "1 · Fetch DOIs", in the window.
_GUI_STEPS = tuple(step for step in SEARCH_STEPS if step[0] != "dois")
_NORMAL_FONT, _BOLD_FONT = ("TkDefaultFont", 11), ("TkDefaultFont", 11, "bold")
_FILTERS = ("Proposed (yes)", "Not proposed (no)", "Downloaded", "Failed or closed", "All")
_COLUMNS = (("decision", "✓", 30), ("score", "score", 46), ("model", "model", 50), ("access", "access", 60),
            ("state", "state", 300),
            ("year", "year", 46), ("title", "title", 330), ("journal", "journal", 150), ("flags", "flags", 150))
CANDIDATES_INFO = ("ⓘ  Every paper the searches found for this job, with its score and its state: to review, "
                   "downloaded (and from where), not downloaded (and why), waiting. Select papers and press ✓ Yes or "
                   "✗ No (or the y and n keys); double-click one for everything known about it.")
_REVIEWABLE = (SCREENED, APPROVED, REJECTED)  # not fetched yet: its decision can still change
_FETCHED = (DOWNLOADED, EXTRACTED)
_MARK = {YES: "✓", NO: "✗"}


def _state(c: Candidate) -> str:
    """Where a candidate stands, in a few words."""
    if c.status in _FETCHED:
        return f"{c.status} ({c.source_used})" if c.source_used else c.status
    if c.status == FAILED and (c.error or "").startswith("waiting"):
        return "waiting — a busy site, tried again"
    if c.status in (FAILED, CLOSED):  # why, in plain words (the details of a row keep the full error)
        tries = f" ({c.attempts}/{MAX_ATTEMPTS} tries)" if c.status == FAILED and c.attempts else ""
        return f"not downloaded{tries} — {by_hand.reason_of(c).lower()}"
    return {SCREENED: "to review", APPROVED: "approved", REJECTED: "rejected"}.get(c.status, c.status)


def _row(c: Candidate) -> Row:
    tags = ("done",) if c.status in _FETCHED else ("failed",) if c.status in (FAILED, CLOSED) else \
        ("no",) if c.decision == NO else ()
    guess = f"{c.model_yes:.2f}" if c.model_yes >= 0 and c.status == SCREENED else ""  # learn.py: its chance of a yes
    return (c.key, [_MARK.get(c.decision, "?"), f"{c.score:g}", guess, c.access, _state(c), str(c.year or ""),
                    c.title, c.journal, " ".join(c.flags)], tags)


def _shown(c: Candidate, wanted: str, text: str) -> bool:
    if text and text not in f"{c.title} {c.journal} {c.doi} {' '.join(c.flags)} {c.publisher}".lower():
        return False
    if wanted == "Downloaded":
        return c.status in _FETCHED
    if wanted == "Failed or closed":
        return c.status in (FAILED, CLOSED)
    if wanted == "Proposed (yes)":
        return c.decision == YES
    if wanted == "Not proposed (no)":
        return c.decision == NO
    return True


# The phases of a search, as the progress line names them: (what is done, the things counted).
_SEARCH_PHASES = {"keywords": ("Searching the keywords", "searches (each keyword in each source)"),
                  "records": ("Completing the new papers' records on OpenAlex", "papers"),
                  "abstracts": ("Looking for the abstracts the records lack", "papers"),
                  "snowball": ("Snowballing", "papers kept"),
                  "screen": ("Scoring the papers against the topic", "papers")}
_KEYWORD_LINE = re.compile(r"^=== \[(?:extra )?(\d+)/(\d+)\] .*\(new DOIs so far: ([^)]*)\)")


def _dois_csv() -> str:
    from WebScraping.Fetch_DOIs.get_dois import OUTPUT
    return str(OUTPUT)


def _dois_txt() -> str:
    return os.path.splitext(_dois_csv())[0] + ".txt"


def _count_lines(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


class _LinesTo:
    """A stdout that hands each line it is given to `write_line` (what a command prints, in the log)."""

    def __init__(self, write_line: Callable[[str], None]):
        self._write_line, self._part = write_line, ""

    def write(self, text: str) -> int:
        self._part += text
        *lines, self._part = self._part.split("\n")
        for line in lines:
            if line.strip():
                self._write_line(line.rstrip())
        return len(text)

    def flush(self) -> None:
        pass


class WebPanel(Pausable, ttk.LabelFrame):
    def __init__(self, parent: tk.Misc, app: "Window", job_path: str, output_dir: str):
        super().__init__(parent, text=" Web articles — search, download and extract ", padding=10)
        # The controls above (they scroll when short), the tabs below, a line to drag between them.
        from LocalExtraction.gui.layout import Stack
        self.stack = Stack(self)
        host = self.stack.host
        self.app = app
        self.job: Optional[Job] = None
        self.harvest: Optional[Harvest] = None
        self.stop_event = runcontrol.RunControl()  # Stop, and Pause / Resume
        self._last_count = ""  # the last answer to "how many new DOIs?", offered again
        self._thread: Optional[threading.Thread] = None
        self._working = False  # a step is under way (set by _run, cleared by the step when it ends)
        self._candidates: Dict[str, Candidate] = {}
        self._papers: List[PaperData] = []
        self._done = self._total = 0
        self._pace = Pace()  # the time left of the step under way (made again as each step starts)

        row = ttk.Frame(host)
        row.pack(fill="x")
        self.job_file = FolderRow(row, "Job file:", job_path, pick="file", file_types=[("Job file", "*.yaml *.yml")],
                                  on_change=self.load_job, label_width=15)
        self.job_file.pack(side="left", fill="x", expand=True)
        self.edit_button = ttk.Button(row, text="Search settings…", command=self._edit_job)
        self.edit_button.pack(side="left", padx=(6, 0))
        when_saved(self._settings_saved)
        self.check_button = ttk.Button(row, text="Check setup", command=self._check)
        self.check_button.pack(side="left", padx=(6, 0))
        # No folder named (here or with --output): the job's own database, which changes with the job (output_for).
        self._output_follows_job = not output_dir
        self.output = FolderRow(host, "Results folder:", output_dir or DEFAULT_OUTPUT, label_width=15,
                                on_change=self._output_chosen)
        self.output.pack(fill="x", pady=(4, 0))
        self.job_summary = tk.StringVar()
        WrapLabel(host, textvariable=self.job_summary, foreground="#8c8c8c").pack(fill="x", pady=(2, 8))

        steps = ttk.Frame(host)
        steps.pack(fill="x")
        self.fetch_dois_button = ttk.Button(steps, text="1 · Fetch DOIs", command=self.fetch_dois)
        self.fetch_dois_button.pack(side="left")
        self.search_button = ttk.Button(steps, text="2 · Search", command=self.search)
        self.search_button.pack(side="left", padx=(6, 0))
        self.download_button = ttk.Button(steps, text="3 · Download", command=self.download)
        self.download_button.pack(side="left", padx=(6, 0))
        self.extract_button = ttk.Button(steps, text="4 · Extract", command=self.extract)
        self.extract_button.pack(side="left", padx=(6, 0))
        from Evaluation.gui import evaluate_button  # how accurate the extraction in the results folder is
        self.evaluate_button = evaluate_button(steps, self.output.get, "web", "web articles")
        self.evaluate_button.pack(side="left", padx=(6, 0))
        self.stop_button = ttk.Button(steps, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(6, 0))
        self.pause_button(steps).pack(side="left", padx=(6, 0))
        # (“☕ Keep the computer awake” is in the window's footer, for long searches and downloads: a second one here
        # took the room of “Delete outputs…”, squeezed to nothing at the window's smallest.)
        # The ledger is let go of while the dialog is open (it may be deleted), and opened again after.
        self.delete_button = delete_outputs_button(steps, "web", before=self.close, after=self._outputs_deleted,
                                                   groups=self.output_groups)
        self.delete_button.pack(side="right")
        # The papers left on the hand list, fetched with the user's own browser (browser_helper.py).
        self.browser_button = ttk.Button(steps, text="Get the rest with my browser…", command=self.open_browser_helper)
        self.browser_button.pack(side="right", padx=(0, 6))
        outputs.register("web", self.running, "a step of the web scraping is running")
        outputs.register("web", self.holds_ledger, "the “Search and download” window has the ledger open: "
                                                   "close it, or delete from that window", groups=("papers",))
        # What "2 · Search" searches with: the DOIs "1 · Fetch DOIs" saved, and the keywords saved in the job.
        uses = ttk.Frame(host)
        uses.pack(fill="x", pady=(6, 0))
        ttk.Label(uses, text="2 · Search uses:", foreground=_QUIET).pack(side="left")
        self.dois_note = tk.StringVar()
        self._dois_label = ttk.Label(uses, textvariable=self.dois_note, font=_BOLD_FONT)
        self._dois_label.pack(side="left", padx=(6, 0))
        self.keywords_note = tk.StringVar()
        WrapLabel(uses, textvariable=self.keywords_note, foreground=_QUIET).pack(side="left", fill="x", expand=True,
                                                                                padx=(6, 0))
        # What "2 · Search" does, step by step: the step under way is marked, the ones done ticked.
        flow = ttk.Frame(host)
        flow.pack(fill="x", pady=(4, 0))
        ttk.Label(flow, text="2 · Search does:", foreground=_QUIET).pack(side="left")
        self._step_labels: Dict[str, ttk.Label] = {}
        for index, (key, _) in enumerate(_GUI_STEPS):
            if index:
                ttk.Label(flow, text="→", foreground=_QUIET).pack(side="left", padx=(6, 0))
            label = ttk.Label(flow, foreground=_QUIET)
            label.pack(side="left", padx=(6, 0))
            self._step_labels[key] = label
        self._step_texts: Dict[str, str] = {"keywords": "① Keyword search", "check": "② Check the new papers",
                                            "snowball": "③ Citations", "screen": "④ Score and propose"}
        self._show_step(None, done=False)
        options = ttk.Frame(host)
        options.pack(fill="x", pady=(6, 0))
        # 2 · Search can go on by itself into 3 · Download, and 3 · Download into 4 · Extract.
        self.search_then_download = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="After 2 · Search, download the papers proposed",
                        variable=self.search_then_download).pack(side="left")
        ttk.Label(options, text="·  Download at most", foreground=_QUIET).pack(side="left", padx=(10, 0))
        self.limit_var = tk.StringVar()
        ttk.Entry(options, textvariable=self.limit_var, width=5).pack(side="left", padx=4)
        ttk.Label(options, text="papers (empty: all)  ·", foreground=_QUIET).pack(side="left")
        self.then_extract = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="then extract them (4 · Extract)", variable=self.then_extract).pack(
            side="left", padx=(6, 0))
        self._chain_download = False  # the search under way goes on into the download (the box above)

        progress = ttk.Frame(host)
        progress.pack(fill="x", pady=(8, 6))
        self.progress = ttk.Progressbar(progress, mode="determinate", length=170)
        self.progress.pack(side="right", padx=(8, 0))
        # The whole step followed in a window of its own: its phases, what is searched or fetched when, the time left.
        self.tracker: Optional[Tracker] = None
        details_button(progress, lambda: self.tracker, "Web scraping").pack(side="right", padx=(8, 0))
        self.status = tk.StringVar()
        self.status_label = WrapLabel(progress, textvariable=self.status)  # dark yellow while a step runs
        self.status_label.pack(side="left", fill="x", expand=True)
        # What the download says of the papers a busy service refused ("too many requests"): they are tried again
        # at the end, one after another and spaced. Shown under the status while it holds, until the next step.
        self.notice = tk.StringVar()
        self._notice_label = WrapLabel(host, textvariable=self.notice, foreground=WARNING_COLOUR)
        self._notice_after = progress
        self.stop_note = stop_note(host)  # while a step runs: what stopping now keeps

        self.book = ttk.Notebook(self)
        self.card = ResultCard(host)  # what the last step did, above the tabs
        self.stack.below(self.book, cards=[self.card])
        self.review = ttk.Frame(self.book, padding=(0, 6, 0, 0))
        WrapLabel(self.review, foreground="#6b7280", justify="left", text=CANDIDATES_INFO).pack(fill="x", pady=(0, 6))
        bar = ttk.Frame(self.review)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Show").pack(side="left")
        self.filter_var = tk.StringVar(value=_FILTERS[0])
        choice = ttk.Combobox(bar, values=_FILTERS, textvariable=self.filter_var, state="readonly", width=17)
        choice.pack(side="left", padx=4)
        choice.bind("<<ComboboxSelected>>", lambda event: self.show_candidates(reload=False))
        ttk.Label(bar, text="containing").pack(side="left", padx=(8, 0))
        self.search_var = tk.StringVar()
        contains = ttk.Entry(bar, textvariable=self.search_var, width=16)
        contains.pack(side="left", padx=4)
        contains.bind("<KeyRelease>", lambda event: self.show_candidates(reload=False))
        decide = ttk.Frame(self.review)
        decide.pack(fill="x", pady=(0, 4))
        ttk.Button(decide, text="✓ Yes", command=lambda: self._decide(YES), width=6).pack(side="left")
        ttk.Button(decide, text="✗ No", command=lambda: self._decide(NO), width=6).pack(side="left", padx=4)
        # The papers screened before, decided again with the settings of now (a box ticked, a word changed).
        self.rescreen_button = ttk.Button(decide, text="Re-screen with the settings…", command=self.rescreen)
        self.rescreen_button.pack(side="right")
        self.counts = tk.StringVar()
        WrapLabel(decide, textvariable=self.counts).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.table = Table(self.review, _COLUMNS, on_open=self._details, stretch="title")
        self.table.tag("no", foreground="#9a9a9a")
        self.table.tag("done", foreground="#1a7f37")
        self.table.tag("failed", foreground="#b3261e")
        self.table.pack(fill="both", expand=True)
        # A long list is reviewed faster from the keyboard: arrows to move, y or n to decide.
        self.table.tree.bind("<KeyPress-y>", lambda event: self._decide(YES))
        self.table.tree.bind("<KeyPress-n>", lambda event: self._decide(NO))
        self.book.add(self.review, text="Candidates")
        from .downloads_view import DownloadsView  # every paper of the last download: got, missed and why, waiting
        self.downloads = DownloadsView(self.book, lambda: self.job.fetch.folder if getattr(self, "job", None) else None,
                                       self._papers_to_get, self._tried_so_far)
        self.book.add(self.downloads, text="Downloads")
        self.energies = EnergiesView(self.book, app, self.output.get)
        self.book.add(self.energies, text="Activation energies")
        from LocalExtraction.gui.verify import verify_tab  # a person checks each value against its page
        self.verify = verify_tab(self.book, self.output.get,
                                 lambda: [self.job.fetch.folder] if self.job is not None else [])
        self.activity = LogPane(self.book, height=14, clearable=True, also_clear=lambda: self.app.log.clear())
        self.book.add(self.activity, text="Activity")

        self.load_job()

    def _tried_so_far(self) -> List[Dict[str, str]]:
        """“Every paper tried so far” of the Downloads tab: each paper the downloads got or tried, as it stands now
        in the ledger (the log only holds the downloads made since it exists)."""
        if getattr(self, "job", None) is None:
            return []
        from .. import download_log
        harvest = self._harvest()
        rows = []
        for c in harvest.ledger.all(DOWNLOADED, EXTRACTED, FAILED, CLOSED):
            row = download_log.entry(c, "so far")
            row["time"] = (c.retrieved_at or "").replace("T", " ")[:19]
            rows.append(row)
        return rows

    def _papers_to_get(self) -> None:
        """“Papers to get by hand…” of the Downloads tab."""
        if self.job is not None:
            self._harvest()
        self.show_missed()

    # ------------------------------------------------------------------
    # The job and its ledger
    # ------------------------------------------------------------------
    def running(self) -> bool:
        """Whether a step is under way. Said by the step itself when it ends — not by its thread being
        alive, which it still is for a moment after it posted that it finished: read then, the buttons
        would stay disabled for good."""
        return self._working

    def show_results(self) -> None:
        self.energies.show()

    def load_job(self) -> None:
        """Reads the job file again and shows what its ledger already holds."""
        if self.running():
            return
        self.close()
        self.job, path = None, self.job_file.get()
        if not path:
            self._no_job("Choose a job file: it says what to search for (configs/sse.yaml is an example), or press Search settings… "
                         "to write one.")
            return
        try:
            self.job = load_job(path)
        except (OSError, ValueError) as error:
            self._no_job(f"This job file cannot be used — {error}")
            return
        self._follow_job()
        search = self.job.search
        years = f" · {search.years[0]}–{search.years[1]}" if search.years else ""
        self.job_summary.set(f"{len(search.queries)} keywords{years} in {len(search.sources)} sources · "
                             f"{len(self.job.fetch.sources)} sources of copies · PDFs go to {self.job.fetch.folder}"
                             f" · extracted into {self.output.get()}")
        self._step_texts = {"keywords": f"① Keywords in {len(search.sources)} sources",
                            "check": "② Check the new papers and the saved DOIs",
                            "snowball": "③ Citations of the papers kept" if search.snowball
                            else "③ Citations: off (job settings)",
                            "screen": "④ Score and propose"}
        self._show_step(None, done=False)
        self._buttons()
        if not os.path.exists(os.path.join(self.job.fetch.folder, "ledger.sqlite")):
            self.show_candidates(papers=[])
            return
        # The window is drawn at once; the decisions of a list reviewed in a spreadsheet, and the list of
        # papers (tens of thousands), are read on a working thread and fill the table when they are in.
        harvest = self._harvest()
        self.counts.set("Reading the list of papers …")
        post = self.app.post

        def read() -> None:
            try:
                harvest.ledger.take_decisions(harvest.review_path)  # a list reviewed in a spreadsheet counts
                papers = harvest.ledger.all()
            except Exception:  # the table is read again by the window then
                papers = None
            post(self._papers_at_open, harvest, papers)
        threading.Thread(target=read, daemon=True).start()

    def _papers_at_open(self, harvest: Harvest, papers: Optional[List[Candidate]]) -> None:
        if harvest is not self.harvest or self.running():
            return  # another job since, or a step under way: it fills the table when it ends
        self.show_candidates(papers=papers)

    def _follow_job(self) -> None:
        """The results folder of the job loaded, unless one was chosen: each job its own database."""
        wanted = output_for(self.job)
        if self._output_follows_job and os.path.normpath(self.output.get()) != os.path.normpath(wanted):
            self.output.set(wanted)
            self.show_results()

    def _output_chosen(self) -> None:
        """A results folder chosen by hand: kept whatever job is chosen next."""
        self._output_follows_job = False
        self.show_results()

    def output_groups(self) -> Tuple[Group, ...]:
        """What “Delete outputs…” offers: the DOI list, the PDF folder and the results folder of this job (the
        usual folders when no job is loaded)."""
        if self.job is None:
            return outputs.PARTS["web"][1]
        dois = self._doi_csv()
        stem = os.path.splitext(os.path.basename(dois))[0]
        names = tuple(stem + ending for ending in (".csv", ".txt", ".searched.json", ".tmp", ".txt.tmp",
                                                   ".searched.json.tmp"))
        return (Group("dois", f"The DOI list of Fetch DOIs ({stem}.csv, {stem}.txt, the searches done)",
                      os.path.dirname(dois) or ".", names),
                Group("papers", "The downloaded PDFs, their records and the ledger of the search", self.job.fetch.folder),
                Group("database", "The extracted web database (tables, workbook, look-up cache)", self.output.get()))

    def _no_job(self, why: str) -> None:
        self.job_summary.set(why)
        self._buttons()
        self.show_candidates()

    def _harvest(self) -> Harvest:
        """The engine of the web side for this job (made on first use: it opens the ledger)."""
        assert self.job is not None
        if self.harvest is None:
            self.harvest = Harvest(self.job, self.output.get())
            self.harvest.watcher.say = lambda text: self.app.post(self.show_status, text)  # its countdown
            self.harvest.on_step = lambda step: self.app.post(self._show_step, step)
            self.harvest.on_line = self._doi_line  # what Fetch DOIs prints, in the log and the status line
            self.harvest.on_notice = lambda text: self.app.post(self.show_notice, text)  # refused for too many requests
            self.harvest.on_progress = lambda *args: self.app.post(self._search_progress, *args)  # how far it is
        self.harvest.output_dir = self.output.get()
        return self.harvest

    def _home_ok(self, what: str) -> bool:
        """The main results folder is there (or was just made again, after it was deleted with this window open):
        the step can go on, with the job and its ledger read again from the new folder."""
        from LocalExtraction.gui.home_guard import ensure_home, home_lost
        lost = home_lost()
        if not ensure_home(self, what):
            return False
        if lost and self.harvest is not None:  # its ledger was in the deleted folder: let go of it, a new one is made
            try:
                self.harvest.ledger.close()
            except Exception:
                pass
            self.harvest = None
        if lost:
            self.load_job()
        return self.job is not None

    def close(self) -> None:
        if self.harvest is not None and not self.running():
            self.harvest.ledger.close()
            self.harvest = None

    def settings_changed(self) -> None:
        """New keys or a new contact address: the next step has to be made with them."""
        self.load_job()

    def _edit_job(self) -> None:
        if self.running():
            messagebox.showinfo("MoukhlijMatExtract", "A step is running: change the settings once it is done.", parent=self)
            return
        path = self.job_file.get()
        if path and os.path.exists(path):
            open_job_settings(self, path, self._job_saved)
        else:
            JobDialog(self, self.job or Job(), path or os.path.join("configs", "my_job.yaml"), self._job_saved)

    def _settings_saved(self, path: str) -> None:
        """Settings saved (from this window's "Search settings…" or another one): this job file reloaded."""
        mine = self.job_file.get()
        if mine and not self.running() and os.path.abspath(mine) == os.path.abspath(path):
            self.load_job()

    def _job_saved(self, path: str) -> None:
        relative = os.path.relpath(path)
        self.job_file.set(relative if not relative.startswith("..") else path)
        self.load_job()

    def _check(self) -> None:
        if self.job is None:
            messagebox.showinfo("MoukhlijMatExtract", "Choose a job file first: the check tries the sources it lists.", parent=self)
            return
        CheckDialog(self, self.app.post, self.job, self.output.get())

    # ------------------------------------------------------------------
    # The candidates and their review
    # ------------------------------------------------------------------
    def show_candidates(self, reload: bool = True, papers: Optional[List[Candidate]] = None) -> None:
        """The Candidates tab. `reload`: read the ledger again (after a step or a decision); without it, a
        filter or a word typed works on the papers already read — tens of thousands of them. `papers`:
        the list a step read on its own thread (the window then reads nothing)."""
        if hasattr(self, "downloads") and (reload or papers is not None):
            self.downloads.show(force=True)  # after a step, or another job: the Downloads tab follows (not per keystroke)
        if papers is not None:
            candidates = papers
            self._candidates = {c.key: c for c in candidates}
        elif reload or not self._candidates:
            candidates = self.harvest.ledger.all() if self.harvest is not None else []
            self._candidates = {c.key: c for c in candidates}
        else:
            candidates = list(self._candidates.values())
        wanted, text = self.filter_var.get(), self.search_var.get().strip().lower()
        self.table.fill([_row(c) for c in candidates if _shown(c, wanted, text)])
        if not candidates:
            self.counts.set("the selected rows. Nothing searched yet: press “2 · Search”." if self.job is not None else "")
        else:
            waiting = [c for c in candidates if c.status in _REVIEWABLE]
            self.counts.set(
                f"the selected rows · {sum(c.decision == YES for c in waiting)} yes, {sum(c.decision == NO for c in waiting)} no"
                f" · {sum(c.status in _FETCHED for c in candidates)} downloaded · "
                f"{sum(c.status in (FAILED, CLOSED) for c in candidates)} failed/closed · {len(self.table)} of {len(candidates)} shown")
        if not self.running():
            self.status.set(f"Ledger: {self.harvest.summary()}." if self.harvest is not None else "")

    def _decide(self, answer: str, keys: Optional[List[str]] = None) -> None:
        """Marks the selected papers yes or no. A paper already fetched keeps its state."""
        if self.harvest is None or self.running():
            return
        changed = 0
        for key in keys if keys is not None else self.table.selected():
            candidate = self._candidates.get(key)
            # A yes or no given here is a person's, also when it confirms the proposal (learn.py learns from it).
            if candidate is not None and candidate.status in _REVIEWABLE and (
                    candidate.decision != answer or candidate.decided_by != "hand"):
                self.harvest.ledger.update(key, decision=answer, decided_by="hand")
                changed += 1
        if changed:
            # The review list is the same list: what was decided here is what the terminal will read.
            self.harvest.ledger.write_review(self.harvest.review_path)
            self.show_candidates()

    def _details(self, key: str) -> None:
        c = self._candidates.get(key)
        if c is None:
            return
        link = f"https://doi.org/{c.doi}" if c.doi else (f"https://arxiv.org/abs/{c.arxiv_id}" if c.arxiv_id else c.landing_url)
        pairs = [("Title", c.title), ("Authors", ", ".join(c.authors) or "NONE"),
                 ("Journal, year", f"{c.journal or 'NONE'}, {c.year or 'NONE'} ({c.publisher or 'publisher unknown'})"),
                 ("Link", link or "NONE"),
                 ("Decision", (c.decision or "none yet") + (" (yours)" if c.decided_by == "hand" else "")),
                 ("Model of your decisions", f"{c.model_yes:.2f} chance of a yes (it decides nothing)"
                  if c.model_yes >= 0 and c.status == SCREENED else "no guess"),
                 ("State", _state(c)),
                 ("Score and why", f"{c.score:g} — {c.why}"), ("Access", f"{c.access} (open-access status: {c.oa_status or 'unknown'})"),
                 ("Flags", " ".join(c.flags) or "none"), ("Found by", "; ".join(c.found_by) or "NONE"),
                 ("Abstract", c.abstract or "NONE"),
                 ("Abstract from", abstract_basis(c))]
        actions: List[Tuple[str, Callable[[], None]]] = []
        if link:
            actions.append(("Open its page", lambda: webbrowser.open(link)))
        if c.status in _REVIEWABLE and not self.running():
            actions += [("✓ Yes", lambda: self._decide(YES, [key])), ("✗ No", lambda: self._decide(NO, [key]))]
        DetailsDialog(self, c.title[:80] or key, pairs, actions)

    # ------------------------------------------------------------------
    # The steps
    # ------------------------------------------------------------------
    def _buttons(self) -> None:
        busy = self.running()
        ready = "normal" if self.job is not None and not busy else "disabled"
        for button in (self.fetch_dois_button, self.search_button, self.download_button, self.extract_button,
                       self.rescreen_button):
            button.configure(state=ready)
        self._show_dois_note()
        self.stop_button.configure(state="normal" if busy else "disabled")
        self.set_pause_button(busy)
        self.edit_button.configure(state="disabled" if busy else "normal")
        self.delete_button.configure(state="disabled" if busy else "normal")
        self.evaluate_button.configure(state="disabled" if busy else "normal")

    def holds_ledger(self) -> bool:
        return self.harvest is not None

    def _outputs_deleted(self, deleted: bool) -> None:
        if deleted:
            self._papers = []
            self.activity.write("--- Outputs deleted.")
        self.load_job()  # the ledger again (a new one if it was deleted), and what it holds
        self.app.database_changed()

    def _steps(self) -> Tuple[ttk.Button, ...]:
        return self.fetch_dois_button, self.search_button, self.download_button, self.extract_button

    def _current(self, button: ttk.Button) -> None:
        """The button of the step that runs now stays blue."""
        theme.mark(button, self._steps())

    def show_notice(self, text: str) -> None:
        """The line of the papers a busy service refused (empty: no line)."""
        self.notice.set(f"⏳ {text}" if text else "")
        if text and not self._notice_label.winfo_manager():
            self._notice_label.pack(fill="x", pady=(0, 6), after=self._notice_after)
        elif not text and self._notice_label.winfo_manager():
            self._notice_label.pack_forget()

    def _run(self, work: Callable[..., None], *arguments: object) -> None:
        """Starts a step on its own thread; `_finished` puts the buttons back whatever happens."""
        self.stop_event.clear()
        self.card.hide()
        self.show_notice("")
        self._started, self._services, self._fetched_titles = time.time(), Counter(), []
        self._pace = Pace()  # the time left of the phase under way
        self._missed: List[Tuple[str, str]] = []  # (key, status) of the papers the download did not get

        def guarded() -> None:
            try:
                with runcontrol.bound(self.stop_event):  # its web requests pause with the step
                    work(*arguments)
            except Stopped:
                self.app.post(self.activity.write, "Stopped before it started.")
            except runcontrol.StepStopped:
                self.app.post(self.activity.write, "Stopped — what was finished is kept.")
            except Exception as error:  # the window must survive a failed step
                self._step_failed = True
                logging.getLogger(__name__).exception("A step of the web scraping failed")
                self.app.post(self.activity.write, f"This step failed: {type(error).__name__}: {error}")
                self.app.post(self.card.show, Card("This step failed", CARD_FAILED, f"{type(error).__name__}: {error}",
                                                   actions=[("Show the log", lambda: self.book.select(self.activity))],
                                                   started=self._started))
            finally:
                # The list of papers for the table, read here — tens of thousands of them: read by the window,
                # it would freeze it for seconds after each step (and after Stop).
                papers = None
                if self.harvest is not None:
                    try:
                        papers = self._papers_read or self.harvest.ledger.all()
                    except Exception:
                        papers = None
                self._papers_read = None
                self._working = False
                self.app.post(self._finished, papers)

        self._working = True
        self._step_failed = False
        self._papers_read = None  # the list of papers a step already read for its card (handed on to the table)
        self._thread = threading.Thread(target=guarded, daemon=True)
        self._thread.start()
        self._buttons()

    def _finished(self, papers: Optional[List[Candidate]] = None) -> None:
        if self.tracker is not None and self.tracker.ended is None:
            self.tracker.finish("failed" if getattr(self, "_step_failed", False) else
                                "stopped" if self.stop_event.is_set() else "done")
        style_running(self.status_label, False)
        show_stop_note(self.stop_note, self.tracker, False)
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        for button in self._steps():
            theme.unmark(button)
        self._buttons()
        self.show_candidates(papers=papers)
        if getattr(self, "_download_next", False):
            self._download_next = False
            self.after(50, lambda: self.download(chained=True))
        self.app.database_changed()

    def stop(self) -> None:
        if self.running():
            self.stop_event.set()
            self.status.set("Stopping — what was found is scored and saved, then the buttons come back (a few seconds) …")
            self.stop_button.configure(state="disabled")
            self._pause.configure(text="Pause", state="disabled", style="TButton")

    # 2 · Search -----------------------------------------------------------
    def search(self) -> None:
        """2 · Search: the keywords saved in the job, and the DOIs "1 · Fetch DOIs" saved — it fetches none."""
        if self.job is None or self.running() or not self._home_ok("The search"):
            return
        s = self.job.search
        saved = _count_lines(self._doi_txt())
        if not saved:
            go_on = messagebox.askyesno(
                "No DOIs saved yet",
                f"The DOI list is empty ({self._doi_csv()}): no DOI has been fetched yet.\n\n"
                "Press “1 · Fetch DOIs” first to collect the DOIs of the topic, then “2 · Search”.\n\n"
                f"Search now with the {len(s.queries)} saved keywords only?", parent=self)
            if not go_on:
                return
        harvest = self._harvest()
        self.status.set(f"Searching with {saved:,} saved DOIs and {len(s.queries)} saved keywords …" if saved else
                        f"Searching with the {len(s.queries)} saved keywords only (no DOI saved) …")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.activity.write(f"--- Search: {len(s.queries)} saved keywords in {', '.join(s.sources)}; "
                            + (f"{saved:,} saved DOIs ({self._doi_csv()})" if saved else "no DOI saved"))
        self._current(self.search_button)
        self._show_step(None, done=False)  # no step ticked yet
        self._chain_download = self.search_then_download.get()
        if self._chain_download:
            self.activity.write("--- Then the papers proposed are downloaded"
                                + (", then extracted." if self.then_extract.get() else "."))
        phases = [("keywords", "Searching the keywords", "searches"),
                  ("records", "Completing the new papers' records (OpenAlex)", "papers"),
                  ("abstracts", "Looking for the missing abstracts", "papers")]
        if s.snowball:
            phases.append(("snowball", "Snowballing", "papers kept"))
        phases.append(("screen", "Scoring the papers against the topic", "papers"))
        self._track("2 · Search", phases, {"keywords": len(s.queries) * len(s.sources)},
                    f"Searching with {saved:,} saved DOIs and {len(s.queries)} saved keywords" if saved else
                    f"Searching with the {len(s.queries)} saved keywords only (no DOI saved)",
                    "the papers found so far are saved and scored, and the next search goes on from there")
        self._run(self._search_work, harvest, self.job_file.get())

    def _search_work(self, harvest: Harvest, job_path: str) -> None:
        added = harvest.discover(job_path=job_path, collect_dois=False)  # the DOIs: those "1 · Fetch DOIs" saved
        harvest.on_step("screen")
        harvest.screen(approve=False)  # the decisions stay proposals: the review is made in the table
        harvest.on_step(None)
        self._papers_read = harvest.ledger.all()  # read here, once: the card and the table use it
        self.app.post(self._searched, added, self._papers_read)

    def _track(self, title: str, phases, totals, what: str, saved: str = "") -> Tracker:
        """A step followed from its start: its estimate in the line (dark yellow until it ends), and the details window
        on it."""
        self.tracker = Tracker("web", f"Web scraping · {title}", phases,
                               controls={"pause": self.toggle_pause, "stop": self.stop,
                                         "paused": lambda: bool(getattr(self.stop_event, "paused", False))},
                               saved_on_stop=saved)
        self.tracker.start(totals)
        self.status.set(self.tracker.start_text(what))
        style_running(self.status_label, True)
        show_stop_note(self.stop_note, self.tracker, True, fill="x", pady=(0, 6), after=self._notice_after)
        from LocalExtraction.gui.single import existing  # an open details window follows the new step
        open_one = existing("progress:Web scraping")
        if open_one is not None:
            open_one.follow(self.tracker)
        return self.tracker

    def _search_progress(self, phase: str, done: int, total: int, detail: str, new: int) -> None:
        """How far the search is, in the status line and the progress bar: the phase, how many of how many, what it
        is asking now, the new papers so far, the time left."""
        if total <= 0 or phase not in _SEARCH_PHASES or not self._working or self.stop_event.is_set():
            return  # (a line that arrives after the step, or once Stop is pressed, does not hide what is said then)
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=total, value=min(done, total))
        title, things = _SEARCH_PHASES[phase]
        tracker = self.tracker
        if tracker is not None and phase in tracker.phases:
            tracker.update(phase, done, total, detail, {"new papers": new} if phase in ("keywords", "snowball") else None)
            self.show_status(tracker.line())  # (a pause or a lost network stays said)
            return
        text = f"{title} — {done:,} of {total:,} {things}"
        if detail:
            text += f" · {detail}"
        if phase in ("keywords", "snowball"):
            text += f" · {new:,} new paper{'' if new == 1 else 's'} so far"
        self.show_status(text + self._pace.left(phase, done, total))

    def _show_step(self, step: Optional[str], done: bool = True) -> None:
        """The step of the search under way (▶, blue) and those done before it (✓, green); `step` None:
        the search is over (every step ticked when `done`, else none)."""
        keys = [key for key, _ in _GUI_STEPS]
        if step is not None and step not in keys:
            return  # a step the window does not show (Fetch DOIs: its own button here)
        current = keys.index(step) if step in keys else (len(keys) if done else -1)
        for index, key in enumerate(keys):
            text = self._step_texts.get(key, key)
            if index < current:
                self._step_labels[key].configure(text="✓ " + text, foreground=_DONE, font=_NORMAL_FONT)
            elif index == current:
                self._step_labels[key].configure(text="▶ " + text, foreground=_NOW, font=_BOLD_FONT)
            else:
                self._step_labels[key].configure(text=text, foreground=_QUIET, font=_NORMAL_FONT)

    def _searched(self, added: int, everything: List[Candidate]) -> None:
        # Searched to the end: the download follows, when asked for, once the buttons are back.
        self._download_next, self._chain_download = self._chain_download and not self.stop_event.is_set(), False
        # Proposed: marked yes and not fetched yet, whatever screening left them as (screened or approved).
        proposed = sum(1 for c in everything if c.status in _REVIEWABLE and c.decision == YES)
        self.activity.write(f"Search {'stopped' if self.stop_event.is_set() else 'finished'}: {added} papers new to "
                            f"the ledger; {proposed} proposed for download. Review them in the Candidates tab, then "
                            "press “3 · Download”.")
        self.filter_var.set(_FILTERS[0])
        self.book.select(self.review)
        self.card.show(self._search_card(added, proposed, everything))

    def _search_card(self, added: int, proposed: int, everything: List[Candidate]) -> Card:
        waiting = [c for c in everything if c.status in _REVIEWABLE and c.decision == YES]
        closed = sum(1 for c in everything if c.status in _REVIEWABLE and "no-open-copy-known" in (c.flags or []))
        best = sorted(waiting, key=lambda c: -c.score)[:3]
        actions = [("Review the candidates", lambda: self.book.select(self.review))]
        if waiting:
            actions.append((f"Download the {number(len(waiting))} proposed", self.download))
        if self.stop_event.is_set():
            return Card("Search stopped", WARNING,
                        f"{number(added)} new paper{'s' if added != 1 else ''} kept. Press “2 · Search” again to go on: "
                        "the searches already answered are skipped, the one cut short is run again.",
                        [Stat(number(added), "new papers", hint=f"{number(len(everything))} in the list"),
                         Stat(number(len(waiting)), "proposed", GOOD, "waiting to be downloaded")],
                        [], [("Search again", self.search), *actions], self._started)
        if not added:
            return Card("Search finished — nothing new", NOTHING,
                        f"The searches gave no paper the list did not have ({number(len(everything))} in it). Change "
                        "or add searches in “Search settings…”.", actions=actions, started=self._started)
        return Card("Search finished", "done",
                    f"{number(added)} new paper{'s' if added != 1 else ''} found; {number(proposed)} proposed for download. "
                    "Check the list in the Candidates tab, then download.",
                    [Stat(number(added), "new papers", hint=f"{number(len(everything))} in the list"),
                     Stat(number(len(waiting)), "proposed", GOOD, "waiting to be downloaded"),
                     Stat(number(closed), "no open copy known", GREY, "kept aside"),
                     Stat(number(_count_lines(self._doi_txt())), "DOIs searched with", hint="saved by “1 · Fetch DOIs”"),
                     *self._watch_stats("search")],
                    [f"Best match: {c.title or c.key} ({c.year or 'year ?'}, score {c.score:g})" for c in best]
                    + self._watch_lines(), actions, self._started)

    # Re-screen ------------------------------------------------------------
    def rescreen(self) -> None:
        """The papers screened before and not downloaded yet, decided again with the job's settings of now."""
        if self.job is None or self.running() or not self._home_ok("The re-screen"):
            return
        harvest = self._harvest()
        waiting = sum(1 for c in self._candidates.values() if c.status in _REVIEWABLE)
        if not waiting:
            messagebox.showinfo("MoukhlijMatExtract", "No paper to re-screen: every paper of the list is downloaded, "
                                "or was tried already.", parent=self)
            return
        closed = ("Papers no free copy is known for are kept: the repositories and the publishers' services are "
                  "asked, and what none of them has goes to the list of papers to download by hand."
                  if self.job.screen.propose_closed else
                  "Papers no free copy is known for are left out. To keep them, tick “Also keep papers no free copy is "
                  "known for” in “Search settings…” → “3 · Which papers” first.")
        if not messagebox.askyesno(
                "Re-screen the papers",
                f"Decide again, with the settings of the job file now, the {waiting:,} paper(s) not downloaded yet?\n\n"
                f"{closed}\n\nA yes or no you set by hand in this table is decided again too. Papers downloaded, "
                "failed or closed are not touched.", parent=self):
            return
        self.status.set(f"Re-screening {waiting:,} paper(s) …")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.activity.write(f"--- Re-screen of {waiting:,} paper(s) with the settings of {self.job_file.get()}")
        self._track("Re-screen", [("screen", "Scoring the papers again", "papers")], {"screen": waiting},
                    f"Re-screening {waiting:,} paper(s)")
        self._run(self._rescreen_work, harvest)

    def _rescreen_work(self, harvest: Harvest) -> None:
        counts = harvest.rescreen()
        self._papers_read = harvest.ledger.all()
        self.app.post(self._rescreened, counts, self._papers_read)

    def _rescreened(self, counts: Dict[str, int], everything: List[Candidate]) -> None:
        waiting = [c for c in everything if c.status in _REVIEWABLE and c.decision == YES]
        changed = counts["proposed"] or counts["dropped"]
        actions = [("Review the candidates", lambda: self.book.select(self.review))]
        if waiting:
            actions.insert(0, (f"Download the {number(len(waiting))} proposed", self.download))
        self.filter_var.set(_FILTERS[0])
        self.book.select(self.review)
        self.card.show(Card(
            "Re-screened", "done" if changed else NOTHING,
            f"{number(counts['rescored'])} paper(s) not downloaded yet decided again with the settings of "
            f"{self.job_file.get()}." + (" Press “3 · Download” to fetch the proposed ones." if waiting else ""),
            [Stat(number(counts["proposed"]), "newly proposed", GOOD),
             Stat(number(counts["dropped"]), "no longer proposed", GREY),
             Stat(number(len(waiting)), "proposed in all", GOOD, "waiting to be downloaded")],
            [], actions, self._started))

    # With DOIs --------------------------------------------------------------
    def results_extra(self) -> List[Tuple[str, str]]:
        """The files of the web scraping kept beside its results folder, for "Browse the CSV files…"."""
        files = [("DOI list of 1 · Fetch DOIs", self._doi_csv())]
        if self.job is not None:
            files.insert(0, ("Candidates of 2 · Search (the review list)",
                             os.path.join(self.job.fetch.folder, "candidates.csv")))
            files.append(("Papers to download by hand", os.path.join(self.job.fetch.folder, HAND_LIST)))
        return files

    def _doi_csv(self) -> str:
        """Where "1 · Fetch DOIs" saves the DOIs and "2 · Search" reads them: the job's doi_list."""
        return self.job.search.doi_list if self.job is not None and self.job.search.doi_list else _dois_csv()

    def _doi_txt(self) -> str:
        return os.path.splitext(self._doi_csv())[0] + ".txt"

    def _show_dois_note(self) -> None:
        """How many DOIs are saved (and when they were fetched), and how many keywords."""
        total = _count_lines(self._doi_txt())
        if total:
            try:
                when = time.strftime(", fetched %d %b %Y %H:%M", time.localtime(os.path.getmtime(self._doi_txt())))
            except OSError:
                when = ""
            self.dois_note.set(f"{total:,} DOIs saved")
            self._dois_label.configure(foreground=_DONE)
            where = f"({self._doi_csv()}{when})"
        else:
            self.dois_note.set("no DOI saved yet")
            self._dois_label.configure(foreground=_EMPTY)
            where = "— press “1 · Fetch DOIs” to collect them"
        keywords = len(self.job.search.queries) if self.job is not None else 0
        self.keywords_note.set(f"{where} · {keywords} keywords saved in the job file")

    def fetch_dois(self) -> None:
        """1 · Fetch DOIs (mme-dois): the job's keywords asked of OpenAlex, Crossref, Semantic Scholar and
        arXiv; the DOIs they give are saved in the DOI list, which "2 · Search" then searches with."""
        if self.job is None or self.running() or not self._home_ok("Fetch DOIs"):
            return
        from LocalExtraction.gui.progress import Timings
        from LocalExtraction.gui.progress_text import duration
        searches = len(self.job.search.queries)
        pace, measured = Timings().seconds("dois")
        estimate = (f"\n\nTime: about {duration(pace * searches)} for the {searches:,} keywords of the job "
                    f"({'from your earlier runs' if measured else 'a first guess, made better by each run'}); "
                    "a number of DOIs asked for can end it sooner.") if searches else ""
        answer = simpledialog.askstring(
            "MoukhlijMatExtract · Fetch DOIs",
            "How many NEW DOIs should be added to the list?\n\nLeave it empty for no limit: the search goes on "
            "until you press Stop (every DOI found is kept). They come from OpenAlex, Crossref, Semantic Scholar "
            "and arXiv, for the searches of the job file." + estimate, initialvalue=self._last_count, parent=self)
        if answer is None:
            return
        answer = answer.strip()
        if answer and not (answer.isdigit() and int(answer) >= 1):
            messagebox.showerror("MoukhlijMatExtract", f"“{answer}” is not a whole number from 1 up (or leave it "
                                 "empty for no limit).", parent=self)
            return
        self._last_count = answer
        count = int(answer) if answer else None
        harvest = self._harvest()
        self.status.set(f"Fetching {count:,} new DOIs …" if count else
                        "Fetching DOIs with no limit — press Stop to end; every DOI found is kept …")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.activity.write("--- Fetch DOIs" + (f": {count:,} new" if count else ": no limit (until Stop)"))
        self.book.select(self.activity)
        self._current(self.fetch_dois_button)
        self._track("1 · Fetch DOIs", [("dois", "Fetch DOIs", "searches")], {"dois": searches},
                    f"Fetching {count:,} new DOIs" if count else "Fetching DOIs with no limit — Stop ends it",
                    "every DOI found so far is saved in the DOI list")
        self._run(self._fetch_dois_work, harvest, count, self.job_file.get())

    def _fetch_dois_work(self, harvest: Harvest, count: Optional[int], job_path: str) -> None:
        import contextlib
        from WebScraping.Fetch_DOIs import get_dois
        before = _count_lines(self._doi_txt())
        argv = (["--count", str(count)] if count else []) + ["--out", self._doi_csv()]
        if job_path and os.path.exists(job_path):
            argv += ["--job", job_path]
        with contextlib.redirect_stdout(_LinesTo(self._doi_line)):
            try:
                get_dois.main(argv)
            except SystemExit as error:  # the command's own way to say it cannot run
                if error.code not in (None, 0):
                    print(f"Fetch DOIs could not run: {error.code}")
        total = _count_lines(self._doi_txt())
        self.app.post(self._dois_fetched, total - before, total, count)

    def _doi_line(self, line: str) -> None:
        self.app.post(self.activity.write, line)
        match = _KEYWORD_LINE.match(line.strip())
        if match:
            self.app.post(self._doi_progress, *match.groups())

    def _doi_progress(self, done: str, total: str, so_far: str) -> None:
        """Fetch DOIs: the search it is at, of how many, the new DOIs so far (of how many asked), the time left."""
        if not self._working or self.stop_event.is_set():
            return
        done_n, total_n = int(done), max(int(total), 1)
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=total_n, value=min(done_n, total_n))
        # (`so_far` is Fetch DOIs' own: “230”, or “230 of 500” when a number of DOIs was asked for)
        if self.tracker is not None and "dois" in self.tracker.phases:
            self.tracker.update("dois", done_n, total_n, "", {"new DOIs so far": so_far})
            self.show_status(self.tracker.line().replace("Fetch DOIs — ", "Fetch DOIs — search ", 1))
            return
        self.show_status(f"Fetch DOIs — search {done_n:,} of {total_n:,} · new DOIs so far: {so_far}"
                         + self._pace.left("dois", done_n, total_n))

    def _dois_fetched(self, new: int, total: int, asked: Optional[int]) -> None:
        stopped = self.stop_event.is_set()
        self._show_dois_note()
        status = WARNING if stopped else "done" if new else NOTHING
        self.card.show(Card(
            "Fetch DOIs stopped" if stopped else "DOIs fetched", status,
            f"{number(new)} new DOI(s) saved" + (f" (you asked for {number(asked)})" if asked else "")
            + f"; {number(total)} DOIs saved in all, in {self._doi_csv()}. Press “2 · Search”: it searches with them "
              "and the saved keywords, and checks each DOI like the keyword results (OpenAlex record, abstract, "
              "topic score).",
            [Stat(number(new), "new DOIs", GOOD if new else GREY), Stat(number(total), "DOIs saved")],
            [], [("2 · Search with them", self.search), ("Show the log", lambda: self.book.select(self.activity))],
            self._started))

    # 3 · Download ---------------------------------------------------------
    def download(self, chained: bool = False) -> None:
        """3 · Download — pressed, or by itself after 2 · Search (`chained`: the box "After 2 · Search, download
        the papers proposed")."""
        if self.job is None or self.running() or not self._home_ok("The download"):
            return
        harvest = self._harvest()
        candidates = list(self._candidates.values()) if chained and self._candidates else harvest.ledger.all()
        # What the fetch will take: every paper marked yes that is not fetched yet, and the failed ones that have tries left.
        wanted = [c for c in candidates if (c.status in _REVIEWABLE and c.decision == YES)
                  or (c.status == FAILED and c.attempts < MAX_ATTEMPTS)]
        hand = by_hand.waiting(harvest.folder)  # PDFs saved by hand: the download is what takes them in
        if not wanted and not hand:
            if chained:  # after a search: said in the log and the status line, no window to close
                waiting = pending_pdfs(harvest.folder, self.output.get()) if self.then_extract.get() else 0
                self.activity.write("Nothing to download after the search: no paper is proposed."
                                    + (f" {waiting} downloaded PDF(s) not extracted yet: extracting them." if waiting else ""))
                self.status.set("Search finished — nothing to download.")
                if waiting:
                    self.extract()
                return
            messagebox.showinfo("MoukhlijMatExtract", "There is nothing to download: no paper is marked yes (search first, "
                                                  "or mark some in the Candidates tab).", parent=self)
            return
        limit: Optional[int] = None
        if self.limit_var.get().strip():
            try:
                limit = max(0, int(self.limit_var.get()))
            except ValueError:
                messagebox.showerror("MoukhlijMatExtract", "“papers at most” is a whole number, or empty for all.", parent=self)
                return
        then_extract = self.then_extract.get()
        if then_extract and not self.app.ready_to_extract(self.output.get()):
            return
        # What the table shows is what gets fetched: the review list is written from it first.
        harvest.ledger.write_review(harvest.review_path)
        self._total, self._done = (min(limit, len(wanted)) if limit is not None else len(wanted)), 0
        self.progress.configure(mode="determinate", maximum=max(self._total, 1), value=0)
        what = f"{self._total} paper(s)" + (f" and the {hand} PDF(s) of the by_hand folder" if hand else "")
        self.status.set(f"Downloading {what} …")
        self.activity.write(f"--- Download of {what} into {self.job.fetch.folder}")
        self.book.select(self.activity)
        self._current(self.download_button)
        phases = [("download", "Downloading the legal copies", "papers")]
        if then_extract:
            phases.append(("extract", "Extracting the PDFs", "PDFs"))
        self._track("3 · Download", phases, {"download": self._total}, f"Downloading {what}",
                    "every PDF downloaded so far is saved, and the next download goes on with the rest"
                    + (" (and what was already extracted stays in the database)" if then_extract else ""))
        self._run(self._download_work, harvest, limit, then_extract, self.output.get(), self.app.workers())

    def _download_work(self, harvest: Harvest, limit: Optional[int], then_extract: bool, output: str, workers: int) -> None:
        results = harvest.fetch(limit=limit, stop_event=self.stop_event,
                                progress_callback=lambda c, outcome, done, total: self.app.post(
                                    self._paper_fetched, c.key, outcome, done, total))
        self.app.post(self.activity.write,
                      f"Download finished: {results.get(DOWNLOADED, 0)} downloaded, {results.get(FAILED, 0)} failed "
                      f"(tried again next time), {results.get(CLOSED, 0)} with no copy to be had, "
                      f"{results.get('waiting', 0)} still refused by a site (the watcher checks them again next time).")
        if not self.stop_event.is_set():
            self.app.post(self._tell_missed, dict(results), harvest.email_problem)
        self._downloads = dict(results)
        # Then extract: what this download brought, and any PDF downloaded before and not extracted yet.
        if then_extract and not self.stop_event.is_set() and (results.get(DOWNLOADED, 0)
                                                              or pending_pdfs(harvest.folder, output)):
            self.app.post(self._current, self.extract_button)  # the download goes on into the extraction
            self._extract_work(harvest, output, workers)
        else:  # nothing new to extract: the card says how the download went
            self._downloads = None
            self.app.post(self._show_download_card, dict(results))

    def _show_download_card(self, results: Dict[str, int]) -> None:
        got, failed, closed = results.get(DOWNLOADED, 0), results.get(FAILED, 0), results.get(CLOSED, 0)
        taken = getattr(self.harvest, "taken_in", 0) or 0  # PDFs of the by_hand folder taken in first
        stopped = self.stop_event.is_set()
        status = WARNING if stopped or (failed and got) else CARD_FAILED if failed and not got else \
            NOTHING if not got and not taken else "done"
        folder = self.job.fetch.folder if self.job else ""
        by_hand_count = len(self._hand_rows())
        actions = [("Extract them", self.extract), ("See every paper of this download",
                                                    lambda: (self.downloads.show(force=True), self.book.select(self.downloads))),
                   ("Open the papers folder", lambda: open_path(folder)), ("Show the log", lambda: self.book.select(self.activity))]
        if by_hand_count:
            actions.insert(1, (f"Papers not downloaded ({number(by_hand_count)})…", self.show_missed))
        self.card.show(Card(
            "Download stopped" if stopped else "Download finished",
            status, f"{number(got)} PDF(s) saved in {folder}."
            + (f" {number(taken)} PDF(s) of the by_hand folder taken in, their source recorded." if taken else "")
            + (" Extract them next (“4 · Extract”)." if got or taken else ""),
            [Stat(number(got), "downloaded", GOOD), Stat(number(failed), "failed", BAD, "tried again next time"),
             *([Stat(number(taken), "taken in by hand", GOOD, "from the by_hand folder")] if taken else []),
             Stat(number(closed), "no copy to be had", GREY),
             *([Stat(number(by_hand_count), "to get by hand", WARNING_COLOUR, "all downloads: see the list")]
               if by_hand_count else []), *self._watch_stats("download")],
            ([self.notice.get()[2:]] if self.notice.get() else [])
            + [f"From {service}: {number(n)}" for service, n in self._services.most_common(3)]
            + [f"Saved: {title}" for title in self._fetched_titles[:2]] + self._watch_lines(),
            actions, self._started))

    def _hand_rows(self, keys: Optional[set] = None) -> List[Dict[str, str]]:
        """The papers the downloads could not get (by_hand.missed_rows): those `keys` only when given."""
        if self.harvest is None:
            return []
        try:
            return by_hand.missed_rows(self.harvest.folder, self.harvest.ledger, keys)
        except Exception as error:  # what shows the list must not stop the window
            logging.warning(f"The papers not downloaded could not be listed: {error}")
            return []

    def show_missed(self, keys: Optional[set] = None, asked: Optional[int] = None) -> None:
        """The window of the papers not downloaded: those of the last download (`keys`), or all of them."""
        rows = self._hand_rows(keys)
        if not rows or self.harvest is None:
            messagebox.showinfo("MoukhlijMatExtract", "Every paper marked yes is downloaded: nothing to get by hand.",
                                parent=self)
            return
        MissedDialog(self, rows, asked, self.harvest.hand_list_path, self.harvest.by_hand_folder,
                     helper=self.open_browser_helper)

    def open_browser_helper(self) -> None:
        """“Get the rest with my browser…”: the papers left on the hand list, opened in the user's browser, their
        PDFs taken in as they arrive in the Downloads folder."""
        if self.job is None:
            messagebox.showinfo("MoukhlijMatExtract", "Choose a job file first.", parent=self)
            return
        self._harvest()
        rows = self._hand_rows()
        if not rows:
            messagebox.showinfo("MoukhlijMatExtract", "Every paper marked yes is downloaded: nothing left to get.",
                                parent=self)
            return
        from LocalExtraction.gui.single import open_once  # one browser helper: asked again, it comes back
        from .browser_helper import BrowserHelperDialog
        open_once("browser-helper", "The browser helper", self, lambda: BrowserHelperDialog(self, self, rows))

    def _paper_fetched(self, key: str, outcome: Outcome, done: int, total: int) -> None:
        self.progress.configure(maximum=max(total, 1), value=done)
        if self.tracker is not None and "download" in self.tracker.phases:
            got = "downloaded" if outcome.status == DOWNLOADED else outcome.status
            self.tracker.update("download", done, total, f"{key}: {got}" + (f" via {outcome.service}" if
                                                                           outcome.service and got == "downloaded" else ""))
            self.show_status(self.tracker.line())
        else:
            self.show_status(f"Downloading — {done:,} of {total:,} papers" + self._pace.left("download", done, total))
        refused = bool(outcome.refused) and outcome.status != DOWNLOADED
        # The line of the paper is the engine's own ("[3/40] downloaded: … via osti"), shown in the Activity tab.
        candidate = self.harvest.ledger.get(key) if self.harvest is not None else None
        if refused:
            pass  # not an answer: neither got nor missed
        elif outcome.status == DOWNLOADED:
            self._services[outcome.service] += 1
            if candidate is not None and candidate.title:
                self._fetched_titles.append(candidate.title)
        else:
            self._missed.append((key, outcome.status))
        if candidate is not None:
            self._candidates[key] = candidate
            self.table.update_row(_row(candidate))
        self.downloads.show()  # its line in the Downloads tab (the log is read at most every 1.5 s)

    def _watch_stats(self, kind: str) -> List[Stat]:
        """The watcher's numbers for a card: what was checked, and what a site refused and still waits."""
        if self.harvest is None:
            return []
        t = self.harvest.watcher.tally
        waiting = len(self.harvest.ledger.watch_list(kind))
        if kind == "search":
            stats = [Stat(number(len(t.keywords)), "keywords checked",
                          hint=f"{number(t.searches_answered)} of {number(t.searches_asked)} searches answered")]
        else:
            stats = [Stat(number(len(t.dois)), "DOIs checked", hint=f"{number(len(t.later))} got on a later try")]
        if waiting:
            stats.append(Stat(number(waiting), "waiting", GREY, "refused by a busy site — checked again later"))
        return stats

    def _watch_lines(self) -> List[str]:
        """The watcher's report in total (every run), for a card."""
        if self.harvest is None:
            return []
        return [line for line in self.harvest.watcher.report() if line.startswith("In total")]

    def _tell_missed(self, results: Dict[str, int], email_problem: str) -> None:
        """A message when the download did not get every paper: the e-mail Unpaywall refused, if that is
        why; else which papers have no legal copy, and what can still be done."""
        missed = self._missed
        if not missed:
            return
        asked = sum(results.get(status, 0) for status in (DOWNLOADED, FAILED, CLOSED)) or len(missed)
        if email_problem:
            email = self.job.email() if self.job is not None else ""
            in_job_file = bool(self.job is not None and self.job.contact_email)
            if messagebox.askyesno(
                    "Your e-mail was refused" if email_problem == REFUSED_EMAIL else "No contact e-mail",
                    f"{len(missed):,} of the {asked:,} paper(s) could not be downloaded.\n\n"
                    f"{email_advice(email, email_problem, in_job_file)}\n\n"
                    + ("Open the job file now?" if in_job_file else "Open “API keys…” now?"), parent=self):
                open_path(self.job_file.get()) if in_job_file else self.app.open_keys()
            return
        keys = {key for key, _ in missed}
        if self._hand_rows(keys):  # all got on a later round of the watcher: nothing to say
            self.show_missed(keys, asked)

    # 4 · Extract ----------------------------------------------------------
    def extract(self) -> None:
        if self.job is None or self.running() or not self._home_ok("The extraction") \
                or not self.app.ready_to_extract(self.output.get()):
            return
        self.book.select(self.activity)
        self._current(self.extract_button)
        self._track("4 · Extract", [("extract", "Extracting the PDFs", "PDFs")], {}, "Extracting the downloaded PDFs",
                    "every PDF already extracted stays in the database, and the next extraction reads only the rest")
        self._run(self._extract_work, self._harvest(), self.output.get(), self.app.workers())

    def _extract_work(self, harvest: Harvest, output: str, workers: int) -> None:
        harvest.output_dir = output
        before = snapshot(output)
        total = pending_pdfs(harvest.folder, output)
        self.app.post(self._extraction_started, total, harvest.folder, output)
        with self.app.writing("Web scraping", output, self.stop_event):
            harvest.extract(max_workers=workers, stop_event=self.stop_event,
                            progress_callback=lambda name, paper: self.app.post(self._paper_extracted, name, paper))
        self.app.post(self._extraction_finished, total, output, before)

    def _extraction_started(self, total: int, folder: str, output: str) -> None:
        self._total, self._done, self._papers, self._failed = total, 0, [], 0
        if self.tracker is not None and "extract" in self.tracker.phases:
            self.tracker.update("extract", 0, total)
        self.progress.configure(mode="determinate", maximum=max(total, 1), value=0)
        self.status.set(f"Extracting {total} downloaded article(s) …" if total else "Every downloaded article is in the database already.")
        self.activity.write(f"--- Extraction of {folder} into {output}: {total} new PDF(s)")

    def _paper_extracted(self, filename: str, paper: Optional[PaperData]) -> None:
        self._done += 1
        self.progress.configure(value=self._done)
        if self.tracker is not None and "extract" in self.tracker.phases:
            self.tracker.update("extract", self._done, self._total, filename)
            self.show_status(self.tracker.line())
        else:
            self.show_status(f"Extracting — {self._done:,} of {self._total:,} PDFs · {filename}"
                             + self._pace.left("extract", self._done, self._total))
        if paper is None:
            self._failed += 1
            self.activity.write(f"[FAILED] {filename}")
            return
        self._papers.append(paper)
        self.activity.write(f"[DONE] {filename}\n{summarize_paper(paper)}")

    def _extraction_finished(self, total: int, output: str = "", before=None) -> None:
        self.activity.write(final_summary(self._papers) if total else "Nothing new to extract.")
        if self._papers:
            self.book.select(self.energies)
        if before is None:
            return
        downloads = getattr(self, "_downloads", None)
        prefix = (f"Downloaded {number(downloads.get(DOWNLOADED, 0))} PDF(s), then extracted them: "
                  if downloads else "")
        self._downloads = None
        workbook = os.path.join(output, "database.xlsx")
        stopped = self.stop_event.is_set()
        self.card.show(extraction_outcome(
            output, before, failed=getattr(self, "_failed", 0), stopped=stopped, started=self._started, prefix=prefix,
            pdfs_pending=pending_pdfs(self.job.fetch.folder, output) if stopped and self.job else None,
            actions=[("Show the activation energies", lambda: self.book.select(self.energies)),
                     ("Check the values (Verify)", lambda: self.book.select(self.verify)),
                     ("Browse every table", self.energies.browse),
                     ("Open the workbook", lambda: open_path(workbook) if os.path.exists(workbook) else None),
                     ("Open the results folder", lambda: open_path(output))]))
