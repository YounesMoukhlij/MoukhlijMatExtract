# WebScraping/gui/dialogs.py
"""The windows that open on top of the window of the web project: the API keys and contact address,
one card per organization (the WebScraping/averageScrap/.env file), the question asked each time the
Web scraping window opens, the job, and the check of the setup."""

import os
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from LocalExtraction.gui.dialogs import Dialog

from ..job import ENV_PATH, ENV_SETTINGS, KEY_GROUPS, Job, KeyGroup, read_env, save_env
from .job_dialog import JobDialog, open_job_settings  # noqa: F401  (the settings form lives in its own file)

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
        # The wheel scrolls this frame only while the pointer is over it. Moving onto one of its cards is
        # reported to the frame as leaving it: the wheel is let go only when the pointer is really out.
        self.bind("<Enter>", lambda event: self._wheel(True))
        self.bind("<Leave>", self._leave)
        self.bind("<Destroy>", lambda event: self._wheel(False) if event.widget is self else None)

    def _inside(self, x_root: int, y_root: int) -> bool:
        widget = self.winfo_containing(x_root, y_root)
        return widget is not None and str(widget).startswith(str(self))

    def _leave(self, event: "tk.Event") -> None:
        if not self._inside(event.x_root, event.y_root):
            self._wheel(False)

    def _wheel(self, on: bool) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            if on:
                self.canvas.bind_all(sequence, self._scroll)
            else:
                self.canvas.unbind_all(sequence)

    def _scroll(self, event: "tk.Event") -> None:
        if not self._inside(event.x_root, event.y_root):
            return
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
        ttk.Label(self.body, wraplength=820, justify="left", foreground="#8c8c8c",
                  text="Every key is optional, and nearly all are free (The Lens comes with your institution's "
                       "subscription): the web search works without any of them, and each one opens more papers (a source whose key is missing is skipped, with a line saying so). They are "
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
                 path: str = ENV_PATH):
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
        SettingsDialog(self, on_saved=saved, path=self._path)

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
