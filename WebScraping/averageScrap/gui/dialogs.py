# WebScraping/gui/dialogs.py
"""The windows that open on top of the window of the web project: the API keys and contact address,
one card per organization (the WebScraping/averageScrap/.env file), the job, and the check of the setup."""

import dataclasses
import os
import re
import tempfile
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from LocalExtraction.gui.dialogs import Dialog

from ..job import (ABSTRACT_SOURCES, ENV_PATH, ENV_SETTINGS, KEY_GROUPS, RESOLVERS, SOURCES, Job, KeyGroup, dump_job,
                   load_job, read_env, save_env)

_CHECKS_PER_ROW = 5
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_SET, _NOT_SET = "✓ set", "not set"


class _Scrollable(ttk.Frame):
    """A frame whose content scrolls up and down (with the bar or the mouse wheel)."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        background = ttk.Style().lookup("TFrame", "background") or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=background)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        # The wheel scrolls this frame only while the pointer is over it.
        self.bind("<Enter>", lambda event: self._wheel(True))
        self.bind("<Leave>", lambda event: self._wheel(False))

    def _wheel(self, on: bool) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            if on:
                self.canvas.bind_all(sequence, self._scroll)
            else:
                self.canvas.unbind_all(sequence)

    def _scroll(self, event: "tk.Event") -> None:
        if getattr(event, "num", 0) in (4, 5):  # Linux
            steps = -1 if event.num == 4 else 1
        else:  # Windows (steps of 120) and macOS (small steps)
            steps = -int(event.delta / 120) if abs(event.delta) >= 120 else -event.delta
        self.canvas.yview_scroll(steps, "units")


class SettingsDialog(Dialog):
    """The API keys and the contact e-mail of the web project, one card per organization: what its
    key opens, which method uses it, whether it is set, and a link to get one. They live in
    WebScraping/averageScrap/.env, which git ignores; nothing here is ever written to a log."""

    def __init__(self, parent: tk.Misc, on_saved: Optional[Callable[[], None]] = None, path: str = ENV_PATH):
        super().__init__(parent, "API keys and contact e-mail", "880x760")
        self._on_saved, self._path = on_saved, path
        stored = read_env(path)
        self._secret = {name: secret for name, _, secret in ENV_SETTINGS}
        self._vars: Dict[str, tk.StringVar] = {}
        self._secret_entries: List[ttk.Entry] = []
        self.status: Dict[str, tk.StringVar] = {}  # organization -> "✓ set" / "not set"
        ttk.Label(self.body, text="API keys, one card per organization", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        ttk.Label(self.body, wraplength=820, justify="left", foreground="#555555",
                  text="Every key is free and optional: the web search works without any of them, and each one "
                       "opens more papers (a source whose key is missing is skipped, with a line saying so). They are "
                       "saved in WebScraping/averageScrap/.env, which git ignores, and never written to a log."
                  ).pack(fill="x", pady=(2, 8))
        cards = _Scrollable(self.body)
        cards.pack(fill="both", expand=True)
        for group in KEY_GROUPS:
            self._card(cards.inner, group, stored)
        bottom = ttk.Frame(self.body)
        bottom.pack(fill="x", pady=(10, 0))
        self._show = tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom, text="Show the keys", variable=self._show, command=self._toggle).pack(side="left")
        ttk.Button(bottom, text="Save", command=self._save).pack(side="right")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right", padx=6)

    def _card(self, parent: tk.Misc, group: KeyGroup, stored: Dict[str, str]) -> None:
        card = ttk.LabelFrame(parent, text=f" {group.organization} ", padding=10)
        card.pack(fill="x", padx=(0, 10), pady=(0, 10))
        head = ttk.Frame(card)
        head.pack(fill="x")
        ttk.Label(head, text=group.opens, wraplength=620, justify="left").pack(side="left", fill="x", expand=True)
        status = tk.StringVar()
        badge = ttk.Label(head, textvariable=status, font=("TkDefaultFont", 11, "bold"))
        badge.pack(side="right", padx=(10, 0))
        ttk.Label(card, text=f"Used by: {group.used_by}", foreground="#666666",
                  font=("TkDefaultFont", 10)).pack(anchor="w", pady=(2, 6))
        boxes = ttk.Frame(card)
        boxes.pack(fill="x")
        for row, (name, label) in enumerate(group.fields):
            ttk.Label(boxes, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            var = tk.StringVar(value=stored.get(name) or os.environ.get(name, ""))
            secret = self._secret.get(name, True)
            entry = ttk.Entry(boxes, textvariable=var, show="•" if secret else "")
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            if secret:
                self._secret_entries.append(entry)
            self._vars[name] = var
        boxes.columnconfigure(1, weight=1)
        # The organization counts as set once its first box (its key) is filled.
        first = self._vars[group.fields[0][0]]

        def refresh(*_: object) -> None:
            filled = bool(first.get().strip())
            status.set(_SET if filled else _NOT_SET)
            badge.configure(foreground="#1a7f37" if filled else "#8a8a8a")
        first.trace_add("write", refresh)
        refresh()
        self.status[group.organization] = status
        if group.signup:
            link, _, how = group.signup.partition(" → ")
            row = ttk.Frame(card)
            row.pack(fill="x", pady=(6, 0))
            ttk.Button(row, text="Get a free key ↗", command=lambda url=link.strip(): webbrowser.open(url)).pack(side="left")
            where = re.sub(r"^https?://", "", link.strip()).rstrip("/")
            ttk.Label(row, text=f"{where}" + (f" — {how}" if how else ""), foreground="#666666", wraplength=600,
                      justify="left", font=("TkDefaultFont", 10)).pack(side="left", padx=8)

    def _toggle(self) -> None:
        for entry in self._secret_entries:
            entry.configure(show="" if self._show.get() else "•")

    def _save(self) -> None:
        values = {name: var.get().strip() for name, var in self._vars.items()}
        email = values.get("MME_EMAIL", "")
        if email and not _EMAIL.fullmatch(email):
            messagebox.showerror("API keys", f"“{email}” does not look like an e-mail address.", parent=self)
            return
        try:
            save_env(values, self._path)
        except (OSError, ValueError) as error:
            messagebox.showerror("API keys", f"The keys could not be saved:\n{error}", parent=self)
            return
        if self._on_saved is not None:
            self._on_saved()
        self.destroy()


def _lines(widget: tk.Text) -> List[str]:
    """The non-empty lines of a text box, also split at commas: one item each."""
    return [item.strip() for line in widget.get("1.0", "end").splitlines() for item in line.split(",") if item.strip()]


class JobDialog(Dialog):
    """The job of the web project as a form: what to search, which papers to keep, where copies are
    looked for, what to extract. Saved as a job file, it is the same job in the terminal."""

    def __init__(self, parent: tk.Misc, job: Job, path: str, on_saved: Callable[[str], None]):
        super().__init__(parent, f"Job: {os.path.basename(path) or 'new'}", "820x700")
        self.job, self.path, self._on_saved = job, path, on_saved
        book = ttk.Notebook(self.body)
        book.pack(fill="both", expand=True)

        # --- Search
        tab = self._tab(book, "1 · Search")
        self.queries = self._text(tab, "What to search for (one query per line)", job.search.queries, 7)
        years = ttk.Frame(tab)
        years.pack(fill="x", pady=(10, 0))
        ttk.Label(years, text="Published from").pack(side="left")
        self.year_from = tk.StringVar(value=str(job.search.years[0]) if job.search.years else "")
        self.year_to = tk.StringVar(value=str(job.search.years[1]) if job.search.years else "")
        ttk.Entry(years, textvariable=self.year_from, width=6).pack(side="left", padx=4)
        ttk.Label(years, text="to").pack(side="left")
        ttk.Entry(years, textvariable=self.year_to, width=6).pack(side="left", padx=4)
        ttk.Label(years, text="(empty: any year)", foreground="#666666").pack(side="left")
        self.max_per_query = self._number(tab, "Papers asked of each source for each query", job.search.max_per_query)
        self.search_sources = {name: tk.BooleanVar(value=name in job.search.sources) for name in SOURCES}
        self._checks(tab, "Search in (a source whose key is missing in Settings is skipped)", self.search_sources)
        self.include_preprints = self._check(tab, "Preprints count too", job.search.include_preprints)
        self.ids_file = self._entry(tab, "A list of papers you already know (a text file: one DOI or arXiv id per line)",
                                    job.search.ids_file)
        self.abstract_sources = self._entry(tab, "A missing abstract is asked of, in this order (empty: nobody)",
                                            ", ".join(job.search.abstract_sources))
        ttk.Label(tab, text="Known: " + ", ".join(ABSTRACT_SOURCES), wraplength=650, justify="left",
                  foreground="#666666").pack(anchor="w")

        # --- Screening
        tab = self._tab(book, "2 · Screening")
        ttk.Label(tab, text="A paper is proposed when its title or abstract has a topic word AND a property word, and "
                            "its score reaches the minimum (title: 2 points, abstract: 1, an excluded word: −3).",
                  wraplength=650, justify="left", foreground="#444444").pack(anchor="w")
        self.topic_words = self._text(tab, "Topic words (one per line)", job.screen.topic_words, 5)
        self.property_words = self._text(tab, "Property words", job.screen.property_words, 4)
        self.exclude_words = self._text(tab, "Excluded words", job.screen.exclude_words, 2)
        self.min_score = self._number(tab, "Minimum score", job.screen.min_score)
        self.propose_closed = self._check(tab, "Also propose papers no open copy is known for (the repositories are "
                                               "asked; what nobody has ends as “closed”)", job.screen.propose_closed)
        self.review = self._check(tab, "In the terminal: stop after the search for a review", job.screen.review)

        # --- Download
        tab = self._tab(book, "3 · Download")
        self.folder = self._entry(tab, "Folder for the downloaded PDFs", job.fetch.folder)
        self.fetch_sources = self._text(tab, "Where a copy is looked for, in this order (one per line)", job.fetch.sources, 14)
        ttk.Label(tab, text="Known: " + ", ".join(RESOLVERS), wraplength=650, justify="left",
                  foreground="#666666").pack(anchor="w")
        self.fetch_workers = self._number(tab, "Downloads at once", job.fetch.workers)
        self.max_pdf_mb = self._number(tab, "Largest PDF accepted (MB)", job.fetch.max_pdf_mb)

        # --- Extraction
        tab = self._tab(book, "4 · Extraction")
        self.properties = self._text(tab, "Properties to keep (one per line; empty: every property)", job.extract.properties, 8)
        ttk.Label(tab, text="Activation_Energy covers every name a paper gives it: migration barrier, energy barrier, Ea, ...",
                  wraplength=650, justify="left", foreground="#666666").pack(anchor="w")
        self.require_material = self._check(tab, "Drop a value that cannot be tied to a material", job.extract.require_material)

        buttons = ttk.Frame(self.body)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(buttons, text="Save as…", command=self._save_as).pack(side="right", padx=4)
        ttk.Button(buttons, text="Save", command=lambda: self._save(self.path)).pack(side="right", padx=4)

    # ------------------------------------------------------------------
    # Form helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _tab(book: ttk.Notebook, title: str) -> ttk.Frame:
        tab = ttk.Frame(book, padding=12)
        book.add(tab, text=title)
        return tab

    @staticmethod
    def _text(parent: tk.Misc, label: str, items: Sequence[str], height: int) -> tk.Text:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(10, 2))
        box = tk.Text(parent, height=height, wrap="none", relief="solid", borderwidth=1, padx=4, pady=3)
        box.insert("1.0", "\n".join(items))
        box.pack(fill="x")
        return box

    @staticmethod
    def _entry(parent: tk.Misc, label: str, value: str) -> tk.StringVar:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(10, 2))
        var = tk.StringVar(value=value)
        ttk.Entry(parent, textvariable=var).pack(fill="x")
        return var

    @staticmethod
    def _number(parent: tk.Misc, label: str, value: float) -> tk.StringVar:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text=label).pack(side="left")
        var = tk.StringVar(value=f"{value:g}")
        ttk.Entry(row, textvariable=var, width=8).pack(side="left", padx=6)
        return var

    @staticmethod
    def _check(parent: tk.Misc, label: str, value: bool) -> tk.BooleanVar:
        var = tk.BooleanVar(value=value)
        ttk.Checkbutton(parent, text=label, variable=var).pack(anchor="w", pady=(10, 0))
        return var

    @staticmethod
    def _checks(parent: tk.Misc, label: str, variables: Dict[str, tk.BooleanVar]) -> None:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(10, 2))
        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        for index, (name, var) in enumerate(variables.items()):
            ttk.Checkbutton(grid, text=name, variable=var).grid(row=index // _CHECKS_PER_ROW,
                                                                column=index % _CHECKS_PER_ROW, sticky="w", padx=(0, 14))

    # ------------------------------------------------------------------
    # Reading the form and saving it
    # ------------------------------------------------------------------
    def _read(self) -> Job:
        """The job the form describes. Raises ValueError with what is wrong in it."""
        def whole(var: tk.StringVar, what: str) -> int:
            try:
                return int(float(var.get()))
            except ValueError:
                raise ValueError(f"{what}: a whole number is expected") from None

        first, last = self.year_from.get().strip(), self.year_to.get().strip()
        if bool(first) != bool(last):
            raise ValueError("Years: give both the first and the last year, or neither")
        try:
            minimum = float(self.min_score.get())
        except ValueError:
            raise ValueError("Minimum score: a number is expected") from None
        job = self.job
        return dataclasses.replace(
            job,
            search=dataclasses.replace(
                job.search, queries=_lines(self.queries), ids_file=self.ids_file.get().strip(),
                years=(whole(self.year_from, "First year"), whole(self.year_to, "Last year")) if first else None,
                sources=[name for name, var in self.search_sources.items() if var.get()],
                max_per_query=whole(self.max_per_query, "Papers per query"), include_preprints=self.include_preprints.get(),
                abstract_sources=[n.strip() for n in self.abstract_sources.get().replace("\n", ",").split(",") if n.strip()]),
            screen=dataclasses.replace(
                job.screen, topic_words=_lines(self.topic_words), property_words=_lines(self.property_words),
                exclude_words=_lines(self.exclude_words), min_score=minimum, review=self.review.get(),
                propose_closed=self.propose_closed.get()),
            fetch=dataclasses.replace(
                job.fetch, folder=self.folder.get().strip(), sources=_lines(self.fetch_sources),
                workers=whole(self.fetch_workers, "Downloads at once"), max_pdf_mb=whole(self.max_pdf_mb, "Largest PDF")),
            extract=dataclasses.replace(job.extract, properties=_lines(self.properties),
                                        require_material=self.require_material.get()))

    def _save_as(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, title="Save the job as", defaultextension=".yaml",
                                            initialdir=os.path.dirname(self.path) or "configs",
                                            filetypes=[("Job file", "*.yaml *.yml")])
        if path:
            self._save(path)

    def _save(self, path: str) -> None:
        try:
            text = dump_job(self._read())
            # The loader is the judge of a job file: what it refuses is not saved.
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as trial:
                trial.write(text)
            try:
                load_job(trial.name)
            finally:
                os.remove(trial.name)
        except (ValueError, OSError) as error:
            messagebox.showerror("Job", str(error), parent=self)
            return
        if os.path.exists(path) and _has_comments(path) and not messagebox.askyesno(
                "Job", f"{os.path.basename(path)} has comments written by hand. Saving here keeps the settings "
                       "but not those comments.\n\nSave here anyway? (“Save as…” writes another file.)", parent=self):
            return
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as error:
            messagebox.showerror("Job", f"The job could not be saved:\n{error}", parent=self)
            return
        self._on_saved(path)
        self.destroy()


def _has_comments(path: str) -> bool:
    """Whether a job file carries more comments than the one line this program writes at its top."""
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for line in f if line.lstrip().startswith("#")) > 1
    except OSError:
        return False


class CheckDialog(Dialog):
    """`--check` in a window: what this setup can reach and whether its keys work."""

    def __init__(self, parent: tk.Misc, post: Callable[..., None], job: Job, output_dir: str):
        super().__init__(parent, "Check of the setup", "760x420")
        self._post = post
        self.text = tk.Text(self.body, wrap="word", relief="flat", padx=8, pady=6, state="disabled")
        self.text.tag_configure("ok", foreground="#1a7f37")
        self.text.tag_configure("no", foreground="#b3261e")
        self.text.pack(fill="both", expand=True)
        ttk.Button(self.body, text="Close", command=self.destroy).pack(anchor="e", pady=(10, 0))
        self._write("Asking each service once …\n", "")
        threading.Thread(target=self._work, args=(job, output_dir), daemon=True).start()

    def _write(self, line: str, tag: str) -> None:
        if not self.winfo_exists():
            return
        self.text.configure(state="normal")
        self.text.insert("end", line, tag)
        self.text.configure(state="disabled")

    def _work(self, job: Job, output_dir: str) -> None:
        from ..doctor import report
        from ..http import PoliteClient
        try:
            lines = report(job, PoliteClient(job.email()), papers_csv=os.path.join(output_dir, "papers.csv"))
        except Exception as error:  # a check must report, not crash
            lines = [(False, f"The check itself failed: {type(error).__name__}: {error}")]
        self._post(self._show, lines)

    def _show(self, lines: Sequence[Tuple[bool, str]]) -> None:
        if not self.winfo_exists():
            return
        if not self.winfo_viewable():
            # Tk stalls when wrapped text is added to a window that is not drawn (the main window
            # minimised, say): the answer waits until this one can be seen.
            self.after(300, lambda: self._show(lines))
            return
        for ok, text in lines:
            self._write(f"{'✓' if ok else '✗'}  {text}\n\n", "ok" if ok else "no")
