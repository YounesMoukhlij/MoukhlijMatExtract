# WebScraping/gui/dialogs.py
"""The windows that open on top of the window of the web project: the API keys and contact address,
one card per organization (the ~/MoukhlijMatExtract/.env file), the question asked each time the
Web scraping window opens, the job, and the check of the setup."""

import os
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from LocalExtraction.gui import layout
from LocalExtraction.gui.dialogs import Dialog

from ..job import ENV_SETTINGS, KEY_GROUPS, Job, KeyGroup, read_env, save_env
from .job_dialog import JobDialog, open_job_settings  # noqa: F401  (the settings form lives in its own file)

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_SET, _NOT_SET = "✓ set", "not set"


from LocalExtraction.gui.widgets import Scrolled as _Scrollable  # noqa: E402  (one scrolling area for every window)


class SettingsDialog(Dialog):
    """The API keys and the contact e-mail of the web project, one card per organization: what its
    key opens, which method uses it, whether it is set, and a link to get one. They live in
    ~/MoukhlijMatExtract/.env, readable by you alone; nothing here is ever written to a log."""

    def __init__(self, parent: tk.Misc, on_saved: Optional[Callable[[], None]] = None, path: Optional[str] = None):
        super().__init__(parent, "API keys and contact e-mail", "880x760")
        self._on_saved, self._path = on_saved, path
        stored = read_env(path)
        self._secret = {name: secret for name, _, secret in ENV_SETTINGS}
        self._vars: Dict[str, tk.StringVar] = {}
        self._secret_entries: List[ttk.Entry] = []
        self.status: Dict[str, tk.StringVar] = {}  # organization -> "✓ set" / "not set"
        ttk.Label(self.body, text="API keys, one card per organization", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        ttk.Label(self.body, wraplength=820, justify="left", foreground="#8c8c8c",
                  text="Every key is optional, and nearly all are free (The Lens comes with your institution's "
                       "subscription): the web search works without any of them, and each one opens more papers (a source whose key is missing is skipped, with a line saying so). They are "
                       "saved in ~/MoukhlijMatExtract/.env, readable by you alone, and never written to a log."
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
        # Opened from a window that holds the mouse (the "Before you start" question), this one takes
        # it while it is open — else its buttons, boxes and scrolling would not answer the mouse — and
        # gives it back when it closes.
        self._held_by = self.grab_current()
        if self._held_by is not None:
            self.after_idle(self._take_mouse)
            self.bind("<Destroy>", self._give_mouse_back, add="+")

    def _take_mouse(self) -> None:
        try:
            if self.winfo_exists():
                self.grab_set()
        except tk.TclError:  # not on screen yet: a grab needs the window drawn
            if self.winfo_exists():
                self.after(100, self._take_mouse)

    def _give_mouse_back(self, event: "tk.Event") -> None:
        if event.widget is not self:
            return
        held = self._held_by
        try:
            if held is not None and held.winfo_exists():
                held.grab_set()
        except tk.TclError:
            pass

    def _card(self, parent: tk.Misc, group: KeyGroup, stored: Dict[str, str]) -> None:
        card = ttk.LabelFrame(parent, text=f" {group.organization} ", padding=10)
        card.pack(fill="x", padx=(0, 10), pady=(0, 10))
        head = ttk.Frame(card)
        head.pack(fill="x")
        ttk.Label(head, text=group.opens, wraplength=620, justify="left").pack(side="left", fill="x", expand=True)
        status = tk.StringVar()
        badge = ttk.Label(head, textvariable=status, font=("TkDefaultFont", 11, "bold"))
        badge.pack(side="right", padx=(10, 0))
        ttk.Frame(card, height=6).pack(fill="x")
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
            ttk.Label(row, text=f"{where}" + (f" — {how}" if how else ""), foreground="#8c8c8c", wraplength=600,
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


class StartDialog(Dialog):
    """Shown each time the Web scraping window opens: the contact e-mail, which it asks for and saves
    as MME_EMAIL, and the API keys, optional. Continue calls on_continue once a valid e-mail is given;
    closing it any other way calls on_cancel."""

    def __init__(self, parent: tk.Misc, on_continue: Callable[[], None], on_cancel: Callable[[], None],
                 path: Optional[str] = None):
        super().__init__(parent, "Web scraping · before you start")
        self._on_continue, self._on_cancel, self._path = on_continue, on_cancel, path
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self._stored = read_env(path).get("MME_EMAIL", "")
        self.email = tk.StringVar(value=self._stored or os.environ.get("MME_EMAIL", ""))

        ttk.Label(self.body, text="Before you start", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        mail = self._section("Your academic e-mail — required",
                             "OpenAlex and Crossref answer faster with it, and Unpaywall, which finds the free copies "
                             "of articles, needs it. Without it fewer articles are found, by keywords or by DOI."
                             " Use your university address; it is sent to these three services only.")
        row = ttk.Frame(mail)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="E-mail:").pack(side="left")
        self.entry = ttk.Entry(row, textvariable=self.email, width=40)
        self.entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.entry.bind("<Return>", lambda event: self._continue())

        keys = self._section("API keys — optional",
                             "Every key opens more papers, and nearly all are free; the search works without them. "
                             "Check which ones you have and add them.")
        ttk.Button(keys, text="API keys…", command=self._keys).pack(anchor="w", pady=(6, 0))

        buttons = ttk.Frame(self.body)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Continue", command=self._continue).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right", padx=6)
        self.entry.focus_set()

    def _section(self, title: str, text: str) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self.body, text=f" {title} ", padding=10)
        frame.pack(fill="x", pady=(10, 0))
        ttk.Label(frame, text=text, wraplength=520, justify="left").pack(anchor="w")
        return frame

    def _keys(self) -> None:
        def saved() -> None:
            email = read_env(self._path).get("MME_EMAIL", "")
            if email and self.winfo_exists():
                self._stored = email
                self.email.set(email)
        from LocalExtraction.gui.single import open_once  # the same API keys window as the Web scraping one's
        open_once("api-keys", "The API keys window", self, lambda: SettingsDialog(self, on_saved=saved, path=self._path))

    def _continue(self) -> None:
        email = self.email.get().strip()
        if not _EMAIL.fullmatch(email):
            messagebox.showerror("Web scraping", "Enter your academic e-mail address to go on (for example "
                                 "name@university.edu)." if not email else
                                 f"“{email}” does not look like an e-mail address.", parent=self)
            return
        if email != self._stored:
            try:
                save_env({"MME_EMAIL": email}, self._path)
            except (OSError, ValueError) as error:
                os.environ["MME_EMAIL"] = email
                messagebox.showwarning("Web scraping", f"The e-mail could not be saved:\n{error}\n\n"
                                       "It is used until this window is closed.", parent=self)
        self.destroy()
        self._on_continue()

    def _cancel(self) -> None:
        self.destroy()
        self._on_cancel()


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


# The colour of each reason a paper was not downloaded (by_hand.REASONS), in the dialog below.
_REASON_COLOURS = {"Site refuses programs": "#d97706", "Subscription needed": "#2563eb", "No open copy found": "#b3261e",
                   "Not found at the sources": "#6b7280", "Site busy or not answering": "#2e9e5b"}
_OPEN_AT_ONCE = 10  # links opened in the browser at once, at most: more asks first


class MissedDialog(Dialog):
    """The papers a download could not get, in one window: how many and why (one line per reason, with what
    to do about it), the papers themselves (double-click opens a paper's page in the browser), and how to
    add their PDFs by hand. `rows` are by_hand.missed_rows; `asked` how many papers the download tried
    (None: the whole list, not one download)."""

    def __init__(self, parent: tk.Misc, rows: Sequence[Dict[str, str]], asked: Optional[int], list_path: str,
                 by_hand_folder: str, helper: Optional[Callable[[], None]] = None):
        from LocalExtraction.gui.widgets import Table, WrapLabel
        from ..by_hand import REASONS
        super().__init__(parent, "Papers not downloaded automatically", "1000x720")
        layout.minimum(self, 800, 620)
        self.rows = {row["key"]: row for row in rows}
        self.list_path, self.folder = list_path, by_hand_folder
        grey = "#8c8c8c"

        # Head: the count, and that these papers can still be had.
        head = ttk.Frame(self.body)
        head.pack(fill="x")
        ttk.Label(head, text="!", foreground="#d97706", font=("TkDefaultFont", 22, "bold")).pack(side="left", padx=(2, 12))
        titles = ttk.Frame(head)
        titles.pack(side="left", fill="x", expand=True)
        count = len(rows)
        ttk.Label(titles, font=("TkDefaultFont", 15, "bold"), text=(
            f"{count:,} of the {asked:,} paper(s) could not be downloaded automatically" if asked else
            f"{count:,} paper(s) not downloaded automatically")).pack(anchor="w")
        WrapLabel(titles, foreground=grey, justify="left", text=(
            "Most of them can still be had: the reason of each says how. They are all listed, with their link, in "
            f"{os.path.basename(list_path)}.")).pack(fill="x", anchor="w")

        # Why: one line per reason, with its count and what to do.
        reasons = ttk.LabelFrame(self.body, text="  Why, and what to do  ", padding=(10, 6))
        reasons.pack(fill="x", pady=(12, 8))
        counts: Dict[str, int] = {}
        for row in rows:
            counts[row["reason"]] = counts.get(row["reason"], 0) + 1
        for line, reason in enumerate(r for r in REASONS if counts.get(r)):
            colour = _REASON_COLOURS.get(reason, grey)
            ttk.Label(reasons, text="●", foreground=colour).grid(row=line, column=0, sticky="w", padx=(0, 6), pady=2)
            ttk.Label(reasons, text=f"{counts[reason]:,}", font=("TkDefaultFont", 11, "bold"), width=6,
                      anchor="e").grid(row=line, column=1, sticky="e", padx=(0, 10))
            ttk.Label(reasons, text=reason, font=("TkDefaultFont", 11, "bold")).grid(row=line, column=2, sticky="w",
                                                                                     padx=(0, 16))
            WrapLabel(reasons, text=REASONS[reason], foreground=grey, justify="left").grid(row=line, column=3, sticky="ew")
        reasons.columnconfigure(3, weight=1)

        # The papers.
        self.table = Table(self.body, [("title", "Title", 420), ("journal", "Journal", 180), ("year", "Year", 56),
                                       ("access", "Open access", 92), ("reason", "Reason", 170)],
                           on_open=lambda key: self._open([key]), stretch="title", height=12)
        for reason, colour in _REASON_COLOURS.items():
            self.table.tag(reason, foreground=colour)
        self.table.fill([(row["key"], (row["title"] or row["doi"], row["journal"], row["year"], row["open_access"],
                                       row["reason"]), (row["reason"],)) for row in rows])
        hint = ttk.Label(self.body, foreground=grey, text="Double-click a paper to open its page in your browser · "
                                                         "click a heading to sort")

        # How to add them by hand.
        steps = ttk.LabelFrame(self.body, text="  Adding a PDF by hand  ", padding=(10, 6))
        for number_, text in enumerate((
                "Open the paper's page (double-click it, or select papers and press “Open in browser”).",
                f"Save its PDF into the by_hand folder ({by_hand_folder}), under any file name.",
                "Run “3 · Download” again: each PDF is checked (its DOI and its title) and taken in, with its source "
                "recorded like any downloaded paper."), 1):
            WrapLabel(steps, justify="left", text=f"{number_}.  {text}").pack(fill="x", anchor="w", pady=1)

        buttons = ttk.Frame(self.body)
        # The rows under the table are given their room first: the table takes what is left.
        buttons.pack(side="bottom", fill="x", pady=(12, 0))
        steps.pack(side="bottom", fill="x", pady=(10, 0))
        hint.pack(side="bottom", anchor="w", pady=(4, 0))
        self.table.pack(fill="both", expand=True)
        if helper is not None:  # the browser helper: pages opened in batches, PDFs taken in as they arrive
            ttk.Button(buttons, text="Get them with my browser…", command=lambda: (self.destroy(), helper())).pack(
                side="left", padx=(0, 6))
        ttk.Button(buttons, text="Open in browser", command=lambda: self._open(self.table.selected())).pack(side="left")
        ttk.Button(buttons, text="Copy the links", command=self._copy).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Open the list (CSV)", command=lambda: self._reveal(list_path)).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Open the by_hand folder", command=lambda: self._reveal(by_hand_folder)).pack(
            side="left", padx=(6, 0))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        self.focus_set()

    def _links(self, keys: Sequence[str]) -> List[str]:
        return [self.rows[key]["link"] for key in keys if key in self.rows and self.rows[key]["link"]]

    def _open(self, keys: Sequence[str]) -> None:
        links = self._links(keys)
        if not links:
            messagebox.showinfo("Open in browser", "Select one or more papers first (click, Shift-click, ⌘/Ctrl-click).",
                                parent=self)
            return
        if len(links) > _OPEN_AT_ONCE and not messagebox.askyesno(
                "Open in browser", f"Open {len(links):,} pages in your browser at once?", parent=self):
            return
        for link in links:
            webbrowser.open(link)

    def _copy(self) -> None:
        links = self._links(self.table.selected() or list(self.rows))
        self.clipboard_clear()
        self.clipboard_append("\n".join(links))
        messagebox.showinfo("Copy the links", f"{len(links):,} link(s) copied, one per line.", parent=self)

    def _reveal(self, path: str) -> None:
        from LocalExtraction.gui.widgets import open_path
        if not os.path.exists(path):
            messagebox.showinfo("MoukhlijMatExtract", f"{path} does not exist yet.", parent=self)
            return
        open_path(path)


class CoverageDialog(Dialog):
    """How far each job's papers went (found → proposed → downloaded → extracted) and the same by publisher
    (coverage.py). Opening it writes the tables and the report into WebScraping/coverage/ of the main folder."""

    def __init__(self, parent: tk.Misc, folder: str = os.path.join("WebScraping", "coverage")):
        from LocalExtraction.gui.widgets import Table, WrapLabel, open_path
        from .. import coverage
        super().__init__(parent, "Coverage of the corpus", "1100x720")
        layout.minimum(self, 820, 560)
        families, publishers = coverage.by_family(), coverage.by_publisher()
        self.folder = coverage.write(folder)
        grey = "#8c8c8c"
        WrapLabel(self.body, foreground=grey, text=(
            "How far the papers of each job went: found by the searches, screened, proposed for download, downloaded "
            "(a legal copy), without a legal copy, and extracted. By publisher, a low share downloaded means that "
            "publisher's papers are under-represented in the corpus — worth saying in the article's limitations.")
                  ).pack(fill="x", pady=(0, 8))

        def pct(rate) -> str:
            return "—" if rate is None else f"{100 * rate:.0f} %"
        self.families = Table(self.body, [("job", "Job", 150), ("found", "Found", 70), ("screened", "Screened", 80),
                                          ("proposed", "Proposed", 80), ("downloaded", "Downloaded", 110),
                                          ("no_copy", "No copy", 70), ("papers", "Papers extracted", 120),
                                          ("energies", "Activation energies", 140)], stretch="job", height=9)
        self.families.fill([(r["job"], (r["job"], r["found"], r["screened"], r["proposed"],
                                        f"{r['downloaded']} ({pct(r['download_rate'])})", r["no_copy"],
                                        r["extracted_papers"], r["activation_energies"]), ())
                            for r in families])
        self.families.pack(fill="both", expand=True)
        ttk.Label(self.body, text="By publisher, every job together — the most proposed first").pack(
            anchor="w", pady=(10, 4))
        self.publishers = Table(self.body, [("publisher", "Publisher", 280), ("found", "Found", 70),
                                            ("proposed", "Proposed", 80), ("downloaded", "Downloaded", 110),
                                            ("no_copy", "No copy", 70)], stretch="publisher", height=9)
        self.publishers.fill([(r["publisher"], (r["publisher"], r["found"], r["proposed"],
                                                f"{r['downloaded']} ({pct(r['download_rate'])})", r["no_copy"]), ())
                              for r in publishers])
        self.publishers.pack(fill="both", expand=True)
        bar = ttk.Frame(self.body)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Open the report folder", command=lambda: open_path(self.folder)).pack(side="left")
        ttk.Label(bar, foreground=grey, text=f"coverage.md and two CSV tables in {self.folder}").pack(
            side="left", padx=10)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
