# gui/dialogs.py
"""The windows that open on top of the main one: the details of a row, the keys and contact
address (the .env file), the job of the web side, and the check of the setup."""

import dataclasses
import os
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from web.job import ENV_SETTINGS, RESOLVERS, SOURCES, Job, dump_job, load_job, read_env, save_env

_WHERE_TO_GET = {
    "ELSEVIER_API_KEY": "free: https://dev.elsevier.com/ → I want an API key (create it on your university's network)",
    "WILEY_TDM_TOKEN": "free: https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining",
    "AUTOMATEXTRACT_EMAIL": "Unpaywall needs one; OpenAlex answers faster with one",
}


class _Dialog(tk.Toplevel):
    """A window that belongs to the main one and closes with Escape."""

    def __init__(self, parent: tk.Misc, title: str, size: str = ""):
        super().__init__(parent)
        self.title(title)
        if size:
            self.geometry(size)
        self.transient(parent.winfo_toplevel())
        self.bind("<Escape>", lambda event: self.destroy())
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)


class DetailsDialog(_Dialog):
    """Everything known about one row, as "name / value" lines that can be selected and copied."""

    def __init__(self, parent: tk.Misc, title: str, pairs: Sequence[Tuple[str, str]],
                 actions: Sequence[Tuple[str, Callable[[], None]]] = ()):
        super().__init__(parent, title, "760x520")
        text = tk.Text(self.body, wrap="word", relief="flat", padx=8, pady=6, font=("TkDefaultFont", 11))
        bar = ttk.Scrollbar(self.body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.tag_configure("name", font=("TkDefaultFont", 10, "bold"), foreground="#555555", spacing1=8)
        for name, value in pairs:
            text.insert("end", f"{name}\n", "name")
            text.insert("end", f"{value}\n")
        text.configure(state="disabled")
        text.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        buttons = ttk.Frame(self.body)
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        for label, action in actions:
            ttk.Button(buttons, text=label, command=lambda act=action: (act(), self.destroy())).pack(side="left", padx=4)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="left", padx=4)
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)


class SettingsDialog(_Dialog):
    """The contact address and the keys of the web side. They live in the .env file next to
    main.py, which git ignores; nothing here is ever written to a log."""

    def __init__(self, parent: tk.Misc, on_saved: Optional[Callable[[], None]] = None):
        super().__init__(parent, "Settings: keys and contact address")
        self._on_saved = on_saved
        stored = read_env()
        self._vars: Dict[str, tk.StringVar] = {}
        self._secret_entries: List[ttk.Entry] = []
        ttk.Label(self.body, text="Every line is optional. The web side works without any of them; each one opens "
                                  "more papers.", wraplength=620, justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
        row = 1
        for name, label, secret in ENV_SETTINGS:
            ttk.Label(self.body, text=label).grid(row=row, column=0, sticky="w", pady=(10, 0), columnspan=2)
            var = tk.StringVar(value=stored.get(name) or os.environ.get(name, ""))
            entry = ttk.Entry(self.body, textvariable=var, width=64, show="•" if secret else "")
            entry.grid(row=row + 1, column=0, sticky="ew", columnspan=2)
            if secret:
                self._secret_entries.append(entry)
            self._vars[name] = var
            if name in _WHERE_TO_GET:
                ttk.Label(self.body, text=_WHERE_TO_GET[name], foreground="#666666",
                          font=("TkDefaultFont", 10)).grid(row=row + 2, column=0, sticky="w", columnspan=2)
            row += 3
        self._show = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="Show the keys", variable=self._show, command=self._toggle).grid(
            row=row, column=0, sticky="w", pady=(12, 0))
        buttons = ttk.Frame(self.body)
        buttons.grid(row=row + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(buttons, text="Save", command=self._save).pack(side="left", padx=4)
        self.body.columnconfigure(0, weight=1)

    def _toggle(self) -> None:
        for entry in self._secret_entries:
            entry.configure(show="" if self._show.get() else "•")

    def _save(self) -> None:
        try:
            save_env({name: var.get() for name, var in self._vars.items()})
        except (OSError, ValueError) as error:
            messagebox.showerror("Settings", f"The settings could not be saved:\n{error}", parent=self)
            return
        if self._on_saved is not None:
            self._on_saved()
        self.destroy()


def _lines(widget: tk.Text) -> List[str]:
    """The non-empty lines of a text box, also split at commas: one item each."""
    return [item.strip() for line in widget.get("1.0", "end").splitlines() for item in line.split(",") if item.strip()]


class JobDialog(_Dialog):
    """The job of the web side as a form: what to search, which papers to keep, where copies are
    looked for, what to extract. Saved as a job file, it is the same job in the terminal."""

    def __init__(self, parent: tk.Misc, job: Job, path: str, on_saved: Callable[[str], None]):
        super().__init__(parent, f"Job: {os.path.basename(path) or 'new'}", "720x640")
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
        self._checks(tab, "Search in", self.search_sources)
        self.include_preprints = self._check(tab, "Preprints count too", job.search.include_preprints)
        self.ids_file = self._entry(tab, "A list of papers you already know (a text file: one DOI or arXiv id per line)",
                                    job.search.ids_file)

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
        self.fetch_sources = self._text(tab, "Where a copy is looked for, in this order (one per line)", job.fetch.sources, 11)
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
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text=label).pack(side="left")
        for name, var in variables.items():
            ttk.Checkbutton(row, text=name, variable=var).pack(side="left", padx=6)

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
                max_per_query=whole(self.max_per_query, "Papers per query"), include_preprints=self.include_preprints.get()),
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


class CheckDialog(_Dialog):
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
        from web.doctor import report
        from web.http import PoliteClient
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
