# WebScraping/gui/panel.py
"""The articles from the web. The steps of `python -m WebScraping` as buttons — search, (review in
the table,) download, extract — run by the same WebScraping.harvest.Harvest, on the same ledger and
review list, so a run started in the terminal goes on here and the other way round."""

import logging
import os
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from LocalExtraction.gui.dialogs import DetailsDialog
from LocalExtraction.gui.results import EnergiesView, pending_pdfs
from LocalExtraction.gui.summary import final_summary, summarize_paper
from LocalExtraction.gui.widgets import FolderRow, LogPane, Row, Stopped, Table, WrapLabel
from LocalExtraction.models import PaperData

from ..fetch import Outcome
from ..harvest import MAX_ATTEMPTS, Harvest
from ..job import Job, load_job
from ..ledger import APPROVED, CLOSED, DOWNLOADED, EXTRACTED, FAILED, NO, REJECTED, SCREENED, YES, Candidate, abstract_basis
from .dialogs import CheckDialog, JobDialog

if TYPE_CHECKING:
    from LocalExtraction.gui.window import Window

_FILTERS = ("Proposed (yes)", "Not proposed (no)", "Downloaded", "Failed or closed", "All")
_COLUMNS = (("decision", "✓", 30), ("score", "score", 46), ("access", "access", 60), ("state", "state", 170),
            ("year", "year", 46), ("title", "title", 330), ("journal", "journal", 150), ("flags", "flags", 150))
_REVIEWABLE = (SCREENED, APPROVED, REJECTED)  # not fetched yet: its decision can still change
_FETCHED = (DOWNLOADED, EXTRACTED)
_MARK = {YES: "✓", NO: "✗"}


def _state(c: Candidate) -> str:
    """Where a candidate stands, in a few words."""
    if c.status in _FETCHED:
        return f"{c.status} ({c.source_used})" if c.source_used else c.status
    if c.status == FAILED:
        return f"failed ({c.attempts} of {MAX_ATTEMPTS} tries): {c.error}"
    if c.status == CLOSED:
        return "closed: " + (c.error or "no copy found")
    return {SCREENED: "to review", APPROVED: "approved", REJECTED: "rejected"}.get(c.status, c.status)


def _row(c: Candidate) -> Row:
    tags = ("done",) if c.status in _FETCHED else ("failed",) if c.status in (FAILED, CLOSED) else \
        ("no",) if c.decision == NO else ()
    return (c.key, [_MARK.get(c.decision, "?"), f"{c.score:g}", c.access, _state(c), str(c.year or ""), c.title,
                    c.journal, " ".join(c.flags)], tags)


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


class WebPanel(ttk.LabelFrame):
    def __init__(self, parent: tk.Misc, app: "Window", job_path: str, output_dir: str):
        super().__init__(parent, text=" Web articles — search, download and extract ", padding=10)
        self.app = app
        self.job: Optional[Job] = None
        self.harvest: Optional[Harvest] = None
        self.stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._candidates: Dict[str, Candidate] = {}
        self._papers: List[PaperData] = []
        self._done = self._total = 0

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.job_file = FolderRow(row, "Job file:", job_path, pick="file", file_types=[("Job file", "*.yaml *.yml")],
                                  on_change=self.load_job, label_width=15)
        self.job_file.pack(side="left", fill="x", expand=True)
        self.edit_button = ttk.Button(row, text="Edit…", command=self._edit_job, width=7)
        self.edit_button.pack(side="left", padx=(6, 0))
        self.check_button = ttk.Button(row, text="Check setup", command=self._check)
        self.check_button.pack(side="left", padx=(6, 0))
        self.output = FolderRow(self, "Results folder:", output_dir, label_width=15, on_change=self.show_results)
        self.output.pack(fill="x", pady=(4, 0))
        self.job_summary = tk.StringVar()
        WrapLabel(self, textvariable=self.job_summary, foreground="#666666").pack(fill="x", pady=(2, 8))

        steps = ttk.Frame(self)
        steps.pack(fill="x")
        self.search_button = ttk.Button(steps, text="1 · Search", command=self.search)
        self.search_button.pack(side="left")
        self.download_button = ttk.Button(steps, text="2 · Download", command=self.download)
        self.download_button.pack(side="left", padx=(6, 0))
        self.extract_button = ttk.Button(steps, text="3 · Extract", command=self.extract)
        self.extract_button.pack(side="left", padx=(6, 0))
        self.stop_button = ttk.Button(steps, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(6, 0))
        options = ttk.Frame(self)
        options.pack(fill="x", pady=(6, 0))
        ttk.Label(options, text="Download at most").pack(side="left")
        self.limit_var = tk.StringVar()
        ttk.Entry(options, textvariable=self.limit_var, width=5).pack(side="left", padx=4)
        ttk.Label(options, text="papers (empty: all),").pack(side="left")
        self.then_extract = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="then extract them", variable=self.then_extract).pack(side="left", padx=(6, 0))

        progress = ttk.Frame(self)
        progress.pack(fill="x", pady=(8, 6))
        self.progress = ttk.Progressbar(progress, mode="determinate", length=170)
        self.progress.pack(side="right", padx=(8, 0))
        self.status = tk.StringVar()
        WrapLabel(progress, textvariable=self.status).pack(side="left", fill="x", expand=True)

        self.book = ttk.Notebook(self)
        self.book.pack(fill="both", expand=True)
        self.review = ttk.Frame(self.book, padding=(0, 6, 0, 0))
        bar = ttk.Frame(self.review)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Show").pack(side="left")
        self.filter_var = tk.StringVar(value=_FILTERS[0])
        choice = ttk.Combobox(bar, values=_FILTERS, textvariable=self.filter_var, state="readonly", width=17)
        choice.pack(side="left", padx=4)
        choice.bind("<<ComboboxSelected>>", lambda event: self.show_candidates())
        ttk.Label(bar, text="containing").pack(side="left", padx=(8, 0))
        self.search_var = tk.StringVar()
        contains = ttk.Entry(bar, textvariable=self.search_var, width=16)
        contains.pack(side="left", padx=4)
        contains.bind("<KeyRelease>", lambda event: self.show_candidates())
        decide = ttk.Frame(self.review)
        decide.pack(fill="x", pady=(0, 4))
        ttk.Button(decide, text="✓ Yes", command=lambda: self._decide(YES), width=6).pack(side="left")
        ttk.Button(decide, text="✗ No", command=lambda: self._decide(NO), width=6).pack(side="left", padx=4)
        self.counts = tk.StringVar()
        WrapLabel(decide, textvariable=self.counts, foreground="#333333").pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.table = Table(self.review, _COLUMNS, on_open=self._details, stretch="title")
        self.table.tag("no", foreground="#9a9a9a")
        self.table.tag("done", foreground="#1a7f37")
        self.table.tag("failed", foreground="#b3261e")
        self.table.pack(fill="both", expand=True)
        # A long list is reviewed faster from the keyboard: arrows to move, y or n to decide.
        self.table.tree.bind("<KeyPress-y>", lambda event: self._decide(YES))
        self.table.tree.bind("<KeyPress-n>", lambda event: self._decide(NO))
        self.book.add(self.review, text="Candidates")
        self.energies = EnergiesView(self.book, app, self.output.get)
        self.book.add(self.energies, text="Activation energies")
        self.activity = LogPane(self.book, height=14)
        self.book.add(self.activity, text="Activity")

        self.load_job()

    # ------------------------------------------------------------------
    # The job and its ledger
    # ------------------------------------------------------------------
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def show_results(self) -> None:
        self.energies.show()

    def load_job(self) -> None:
        """Reads the job file again and shows what its ledger already holds."""
        if self.running():
            return
        self.close()
        self.job, path = None, self.job_file.get()
        if not path:
            self._no_job("Choose a job file: it says what to search for (configs/sse.yaml is an example), or press Edit… "
                         "to write one.")
            return
        try:
            self.job = load_job(path)
        except (OSError, ValueError) as error:
            self._no_job(f"This job file cannot be used — {error}")
            return
        search = self.job.search
        years = f" · {search.years[0]}–{search.years[1]}" if search.years else ""
        self.job_summary.set(f"{len(search.queries)} queries{years} · {len(self.job.fetch.sources)} sources of copies · "
                             f"PDFs go to {self.job.fetch.folder}")
        self._buttons()
        if os.path.exists(os.path.join(self.job.fetch.folder, "ledger.sqlite")):
            harvest = self._harvest()
            harvest.ledger.take_decisions(harvest.review_path)  # a list reviewed in a spreadsheet counts
        self.show_candidates()

    def _no_job(self, why: str) -> None:
        self.job_summary.set(why)
        self._buttons()
        self.show_candidates()

    def _harvest(self) -> Harvest:
        """The engine of the web side for this job (made on first use: it opens the ledger)."""
        assert self.job is not None
        if self.harvest is None:
            self.harvest = Harvest(self.job, self.output.get())
        self.harvest.output_dir = self.output.get()
        return self.harvest

    def close(self) -> None:
        if self.harvest is not None and not self.running():
            self.harvest.ledger.close()
            self.harvest = None

    def settings_changed(self) -> None:
        """New keys or a new contact address: the next step has to be made with them."""
        self.load_job()

    def _edit_job(self) -> None:
        if self.running():
            return
        JobDialog(self, self.job or Job(), self.job_file.get() or os.path.join("configs", "my_job.yaml"), self._job_saved)

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
    def show_candidates(self) -> None:
        candidates = self.harvest.ledger.all() if self.harvest is not None else []
        self._candidates = {c.key: c for c in candidates}
        wanted, text = self.filter_var.get(), self.search_var.get().strip().lower()
        self.table.fill([_row(c) for c in candidates if _shown(c, wanted, text)])
        if not candidates:
            self.counts.set("the selected rows. Nothing searched yet: press “1 · Search”." if self.job is not None else "")
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
            if candidate is not None and candidate.status in _REVIEWABLE and candidate.decision != answer:
                self.harvest.ledger.update(key, decision=answer)
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
                 ("Link", link or "NONE"), ("Decision", c.decision or "none yet"), ("State", _state(c)),
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
        for button in (self.search_button, self.download_button, self.extract_button):
            button.configure(state=ready)
        self.stop_button.configure(state="normal" if busy else "disabled")
        self.edit_button.configure(state="disabled" if busy else "normal")

    def _run(self, work: Callable[..., None], *arguments: object) -> None:
        """Starts a step on its own thread; `_finished` puts the buttons back whatever happens."""
        self.stop_event.clear()

        def guarded() -> None:
            try:
                work(*arguments)
            except Stopped:
                self.app.post(self.activity.write, "Stopped before it started.")
            except Exception as error:  # the window must survive a failed step
                logging.getLogger(__name__).exception("A step of the web scraping failed")
                self.app.post(self.activity.write, f"This step failed: {type(error).__name__}: {error}")
            finally:
                self.app.post(self._finished)

        self._thread = threading.Thread(target=guarded, daemon=True)
        self._thread.start()
        self._buttons()

    def _finished(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._buttons()
        self.show_candidates()
        self.app.database_changed()

    def stop(self) -> None:
        if self.running():
            self.stop_event.set()
            self.status.set("Stopping — what is in progress is finished first …")
            self.stop_button.configure(state="disabled")

    # 1 · Search -----------------------------------------------------------
    def search(self) -> None:
        if self.job is None or self.running():
            return
        harvest = self._harvest()
        self.status.set("Searching and screening … (about a minute for a few queries)")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.activity.write(f"--- Search: {len(self.job.search.queries)} queries in {', '.join(self.job.search.sources)}")
        self._run(self._search_work, harvest)

    def _search_work(self, harvest: Harvest) -> None:
        added = harvest.discover()
        harvest.screen(approve=False)  # the decisions stay proposals: the review is made in the table
        self.app.post(self._searched, added)

    def _searched(self, added: int) -> None:
        proposed = sum(1 for c in self.harvest.ledger.all(SCREENED) if c.decision == YES) if self.harvest else 0
        self.activity.write(f"Search finished: {added} papers new to the ledger; {proposed} proposed for download. "
                            "Review them in the Candidates tab, then press “2 · Download”.")
        self.filter_var.set(_FILTERS[0])
        self.book.select(self.review)

    # 2 · Download ---------------------------------------------------------
    def download(self) -> None:
        if self.job is None or self.running():
            return
        harvest = self._harvest()
        candidates = harvest.ledger.all()
        # What the fetch will take: every paper marked yes that is not fetched yet, and the failed ones that have tries left.
        wanted = [c for c in candidates if (c.status in _REVIEWABLE and c.decision == YES)
                  or (c.status == FAILED and c.attempts < MAX_ATTEMPTS)]
        if not wanted:
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
        self.status.set(f"Downloading {self._total} paper(s) …")
        self.activity.write(f"--- Download of {self._total} paper(s) into {self.job.fetch.folder}")
        self.book.select(self.activity)
        self._run(self._download_work, harvest, limit, then_extract, self.output.get(), self.app.workers())

    def _download_work(self, harvest: Harvest, limit: Optional[int], then_extract: bool, output: str, workers: int) -> None:
        results = harvest.fetch(limit=limit, stop_event=self.stop_event,
                                progress_callback=lambda c, outcome, done, total: self.app.post(
                                    self._paper_fetched, c.key, outcome, done, total))
        self.app.post(self.activity.write,
                      f"Download finished: {results.get(DOWNLOADED, 0)} downloaded, {results.get(FAILED, 0)} failed "
                      f"(tried again next time), {results.get(CLOSED, 0)} with no copy to be had.")
        if then_extract and not self.stop_event.is_set():
            self._extract_work(harvest, output, workers)

    def _paper_fetched(self, key: str, outcome: Outcome, done: int, total: int) -> None:
        self.progress.configure(maximum=max(total, 1), value=done)
        self.status.set(f"Downloading: {done} / {total}")
        detail = f"via {outcome.service}" if outcome.status == DOWNLOADED else outcome.error
        self.activity.write(f"[{done}/{total}] {outcome.status}: {key} {detail}")
        candidate = self.harvest.ledger.get(key) if self.harvest is not None else None
        if candidate is not None:
            self._candidates[key] = candidate
            self.table.update_row(_row(candidate))

    # 3 · Extract ----------------------------------------------------------
    def extract(self) -> None:
        if self.job is None or self.running() or not self.app.ready_to_extract(self.output.get()):
            return
        self.book.select(self.activity)
        self._run(self._extract_work, self._harvest(), self.output.get(), self.app.workers())

    def _extract_work(self, harvest: Harvest, output: str, workers: int) -> None:
        harvest.output_dir = output
        total = pending_pdfs(harvest.folder, output)
        self.app.post(self._extraction_started, total, harvest.folder, output)
        with self.app.writing("Web scraping", output, self.stop_event):
            harvest.extract(max_workers=workers, stop_event=self.stop_event,
                            progress_callback=lambda name, paper: self.app.post(self._paper_extracted, name, paper))
        self.app.post(self._extraction_finished, total)

    def _extraction_started(self, total: int, folder: str, output: str) -> None:
        self._total, self._done, self._papers = total, 0, []
        self.progress.configure(mode="determinate", maximum=max(total, 1), value=0)
        self.status.set(f"Extracting {total} downloaded article(s) …" if total else "Every downloaded article is in the database already.")
        self.activity.write(f"--- Extraction of {folder} into {output}: {total} new PDF(s)")

    def _paper_extracted(self, filename: str, paper: Optional[PaperData]) -> None:
        self._done += 1
        self.progress.configure(value=self._done)
        self.status.set(f"Extracting: {self._done} / {self._total} — {filename}")
        if paper is None:
            self.activity.write(f"[FAILED] {filename}")
            return
        self._papers.append(paper)
        self.activity.write(f"[DONE] {filename}\n{summarize_paper(paper)}")

    def _extraction_finished(self, total: int) -> None:
        self.activity.write(final_summary(self._papers) if total else "Nothing new to extract.")
        if self._papers:
            self.book.select(self.energies)
