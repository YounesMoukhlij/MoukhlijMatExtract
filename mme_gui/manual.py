# mme_gui/manual.py
"""The hub's Manual: every command of the project with all of its options.

The options are not copied here: each command is asked for its own `--help` (in a separate Python,
in the background), so the manual always says what the installed program does. The make shortcuts
are read from the Makefile when the project folder is there. tkinter is imported lazily."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

# The folder that holds mme_gui, LocalExtraction, … (the project folder, or site-packages).
ROOT = Path(__file__).resolve().parent.parent
_BLUE = "#1f5f99"


class Command(NamedTuple):
    name: str          # how it is typed once installed: mme-local
    module: str        # the python -m form: LocalExtraction
    args: Tuple[str, ...]  # its sub-command, if any: ("extract",)
    part: str          # the part of the program it belongs to
    what: str          # what it does, in a few words
    make: str          # the make shortcut, "" when there is none

    @property
    def python_form(self) -> str:
        return " ".join(("python -m", self.module, *self.args))


COMMANDS: List[Command] = [
    Command("mme", "mme_gui.commands", (), "Every command", "every command in one: mme help, mme commands, mme <part> …",
            "make help"),
    Command("mme-gui", "mme_gui", (), "The one window", "opens the main window: one button per part", "make gui"),
    Command("mme-local", "LocalExtraction", ("extract",), "1 · Local extraction",
            "reads your PDFs into a database", "make local"),
    Command("mme-local gui", "LocalExtraction", ("gui",), "1 · Local extraction", "the same, in its window",
            "make local-gui"),
    Command("mme-dois", "WebScraping.Fetch_DOIs.get_dois", (), "2 · Web scraping",
            "1 · Fetch DOIs: collects the DOIs of the topic", "make doi"),
    Command("mme-web", "WebScraping", ("run",), "2 · Web scraping",
            "search, review, download and extract", "make web"),
    Command("mme-web gui", "WebScraping", ("gui",), "2 · Web scraping", "the same, in its window", "make web-gui"),
    Command("mme-web update", "WebScraping", ("update",), "2 · Web scraping",
            "every job run before, searched for the papers published since", "make update"),
    Command("mme-web coverage", "WebScraping", ("coverage",), "2 · Web scraping",
            "how far each job's papers went, and by publisher", "make coverage"),
    Command("mme-rank", "SelectingTopMaterial", (), "3 · Ranking",
            "ranks the materials by activation energy", "make rank"),
    Command("mme-rank gui", "SelectingTopMaterial", ("gui",), "3 · Ranking", "the same, in its window",
            "make rank-gui"),
    Command("mme-classify", "Classification", (), "4 · Classification",
            "sorts the materials by crystal and structure family", "make classify"),
    Command("mme-classify gui", "Classification", ("gui",), "4 · Classification", "the same, in its window",
            "make classify-gui"),
    Command("mme-ml-export", "MLDataset", (), "5 · ML datasets",
            "prepares a dataset for machine learning into Ready for ML/", "make ml-export"),
    Command("mme-ml-export gui", "MLDataset", ("gui",), "5 · ML datasets", "the same, step by step in its window",
            "make ml-gui"),
    Command("mme-eval sheet", "Evaluation", ("sheet",), "Evaluation",
            "draws papers, writes the workbook to annotate", "make eval-sheet"),
    Command("mme-eval score", "Evaluation", ("score",), "Evaluation",
            "precision, recall, F1 against the annotations", "make eval-score"),
    Command("mme-eval agree", "Evaluation", ("agree",), "Evaluation",
            "agreement of two annotators", "make eval-agree"),
    Command("mme-eval reference", "Evaluation", ("reference",), "Evaluation",
            "recall against curated databases (OBELiX, Liverpool)", "make eval-reference"),
    Command("mme-release", "Release", (), "Release",
            "the dataset, ready to deposit (Zenodo)", "make release"),
]

# "§ " heading, "• " bullet, "$ " a command to type, "| " a fixed-width line, blank line a gap.
START = """
§ Start here
• Every command runs inside the project's venv. Open a terminal in the project folder, then:
$ source .venv/bin/activate              (Windows: .venv\\Scripts\\activate)
• mme-gui opens the main window. Every part also runs from the terminal, with the commands below.
• Each mme-* command has a python -m form that works without installing the project
  (mme-local = python -m LocalExtraction extract), and a make shortcut (make local).
• Any command followed by --help prints the options listed in this manual.
• Folders you give are relative to ~/MoukhlijMatExtract, where everything is saved.
• Stop a command with Ctrl-C: what is done is kept, and the next run goes on from there.

§ Typical runs
$ mme-local                              read the PDFs of LocalExtraction/papers
$ mme-local --input ~/Downloads/pdfs     read the PDFs of another folder
$ mme-dois --count 500                   1 · Fetch DOIs: add 500 new DOIs to the list
$ mme-web                                2 · Search (keywords + saved DOIs), then stop for your review
$ mme-web --stage fetch --limit 50       after the review: download 50 approved papers, extract them
$ mme-web --dois                         only the saved DOIs: check, download, extract
$ mme-web --check                        test the network, the API keys and the folders
$ mme-web --job configs/cathode.yaml --output WebScraping/web_output_cathode     the same for cathodes
$ mme-web --job configs/anode.yaml --output WebScraping/web_output_anode         … and for anodes
$ mme-local --domain cathode --input ~/pdfs/cathodes --output LocalExtraction/output_cathode
$ mme-rank --component bulk --element Li --top 20
$ mme-rank --kind arrhenius --origin experimental --attribution this-work     one kind of energy, measured
$ mme-rank --domain cathode --source WebScraping/web_output_cathode            a cathode database
$ mme-classify --force                   classify again even when nothing changed
$ mme-eval sheet --papers 60             draw 60 papers to annotate (accuracy of the extraction)
$ mme-eval score                         precision, recall, F1 from the annotated workbook
$ mme-release                            the dataset in one .zip, ready for Zenodo
$ mme commands                           every option of every command (docs/COMMANDS.md)
"""


def overview() -> List[str]:
    """The "every command at a glance" table, as fixed-width lines."""
    rows = [("Command", "Same as", "make", "What it does")]
    rows += [(c.name, c.python_form, c.make or "–", c.what) for c in COMMANDS]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    lines = []
    for n, row in enumerate(rows):
        lines.append("   ".join(cell.ljust(w) for cell, w in zip(row, widths)) + "   " + row[3])
        if n == 0:
            lines.append("   ".join("─" * w for w in widths) + "   " + "─" * len(row[3]))
    return lines


def make_lines(root: Path = ROOT) -> List[str]:
    """The lines `make help` prints, read from the Makefile; [] when there is no Makefile (installed
    with pip, without the project folder)."""
    try:
        text = (root / "Makefile").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines: List[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("help:"):
            inside = True
            continue
        if not inside:
            continue
        if not line.startswith("\t"):
            break
        found = re.match(r'\t@echo "(.*)"\s*$', line)
        if found and "$(" not in found.group(1):  # the line naming the venv's python is left out
            lines.append(found.group(1).replace('\\"', '"'))
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


# ---- the options of each command, from its own --help ------------------------------------------------

_HELP: Dict[Tuple[str, Tuple[str, ...]], str] = {}  # read once per session
_HELP_LOCK = threading.Lock()
_POOL: Optional[ThreadPoolExecutor] = None


def help_text(command: Command, timeout: float = 90) -> Tuple[bool, str]:
    """(True, the --help of `command`) or (False, why it could not be read). Runs it in a separate
    Python, so nothing of the command (folders, logging, Tk) touches this one."""
    key = (command.module, command.args)
    with _HELP_LOCK:
        if key in _HELP:
            return True, _HELP[key]
    env = dict(os.environ, COLUMNS="100", NO_COLOR="1", PYTHONIOENCODING="utf-8",
               MME_AS_COMMAND="1")  # each help names its mme-* command, as a user types it
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(ROOT), os.environ.get("PYTHONPATH", "")) if p)
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        done = subprocess.run([sys.executable, "-P", "-m", command.module, *command.args, "--help"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env, cwd=str(ROOT), stdin=subprocess.DEVNULL, **extra)
    except subprocess.TimeoutExpired:
        return False, f"It did not answer within {timeout:.0f} s."
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"It could not be started: {error}"
    text = done.stdout.strip("\n")
    if done.returncode != 0 or not text:
        tail = "\n".join(done.stderr.strip().splitlines()[-6:])
        return False, f"It ended with code {done.returncode}." + (f"\n{tail}" if tail else "")
    with _HELP_LOCK:
        _HELP[key] = text
    return True, text


def read_all() -> Dict[Command, Future]:
    """Starts reading every command's --help in the background; one future per command."""
    global _POOL
    if _POOL is None:
        _POOL = ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 2), thread_name_prefix="mme-manual")
    return {command: _POOL.submit(help_text, command) for command in COMMANDS}


# ---- the window ----------------------------------------------------------------------------------------

def mono(size: int, weight: str = "normal") -> tuple:
    """The platform's fixed-width font (Menlo, Consolas, DejaVu Sans Mono, …). ("TkFixedFont", 11) would
    not do: Tk reads it as a family that does not exist and falls back to a proportional font."""
    from tkinter import font
    return (font.nametofont("TkFixedFont").actual("family"), size, weight)


def open_manual(parent) -> "object":
    """The Manual window: what is fixed is shown at once, each command's options as they come."""
    import tkinter as tk
    from tkinter import ttk

    win = tk.Toplevel(parent)
    win.title("MoukhlijMatExtract · Manual — every command and its options")
    from LocalExtraction.gui import layout
    layout.place(win, (1000, 720), (700, 460), parent=parent)
    try:
        win.transient(parent.winfo_toplevel())
    except Exception:
        pass
    win.bind("<Escape>", lambda event: win.destroy())

    # Find, at the top
    top = ttk.Frame(win, padding=(12, 10, 12, 4))
    top.pack(fill="x")
    ttk.Label(top, text="Find:").pack(side="left")
    query = tk.StringVar()
    entry = ttk.Entry(top, textvariable=query, width=34)
    entry.pack(side="left", padx=(6, 6))
    next_button = ttk.Button(top, text="Next")
    next_button.pack(side="left")
    found_label = ttk.Label(top, foreground="#8c8c8c")
    found_label.pack(side="left", padx=10)
    status = ttk.Label(top, foreground="#8c8c8c")
    status.pack(side="right")

    # The sections on the left, the text on the right
    panes = ttk.PanedWindow(win, orient="horizontal")
    panes.pack(fill="both", expand=True, padx=12)
    left = ttk.Frame(panes)
    sections = tk.Listbox(left, activestyle="none", exportselection=False, borderwidth=0, highlightthickness=0,
                          font=("TkDefaultFont", 12), width=26, background="#f2f5f8", foreground="#143a5c",
                          selectbackground=_BLUE, selectforeground="white")
    sections.pack(fill="both", expand=True)
    panes.add(left, weight=0)
    right = ttk.Frame(panes)
    text = tk.Text(right, wrap="word", padx=18, pady=12, relief="flat", font=("TkDefaultFont", 11),
                   background="white", foreground="#222222", undo=False)
    bar = ttk.Scrollbar(right, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    panes.add(right, weight=1)

    text.tag_configure("h", font=("TkDefaultFont", 15, "bold"), foreground="#143a5c", spacing1=16, spacing3=6)
    text.tag_configure("cmdhead", font=mono(13, "bold"), foreground="#143a5c", spacing1=18, spacing3=2)
    text.tag_configure("note", foreground="#666666", spacing3=6)
    text.tag_configure("bullet", lmargin1=18, lmargin2=34, spacing3=2)
    text.tag_configure("cont", lmargin1=34, lmargin2=34, spacing3=2)
    text.tag_configure("cmd", font=mono(11), foreground="#8a3b00", lmargin1=34, lmargin2=34,
                       spacing1=1, spacing3=1)
    text.tag_configure("fixed", font=mono(11), lmargin1=18, lmargin2=18, wrap="none")
    text.tag_configure("pending", foreground="#8c8c8c", lmargin1=18, font=("TkDefaultFont", 11, "italic"))
    text.tag_configure("error", foreground="#c62828", lmargin1=18, lmargin2=18)
    text.tag_configure("found", background="#ffe58a")
    text.tag_configure("current", background="#ffb84d")

    titles: List[Tuple[str, str]] = []  # (title in the list, mark in the text)

    def heading(title: str, tag: str = "h", listed: Optional[str] = None) -> None:
        mark = f"section{len(titles)}"
        text.mark_set(mark, "end-1c")
        text.mark_gravity(mark, "left")
        text.insert("end", title + "\n", tag)
        titles.append((listed or title, mark))

    def write_marked(block: str) -> None:
        for line in block.strip("\n").splitlines():
            if line.startswith("§ "):
                heading(line[2:])
            elif line.startswith("$ "):
                text.insert("end", line[2:] + "\n", "cmd")
            elif line.startswith("• "):
                text.insert("end", line + "\n", "bullet")
            elif line.startswith("  ") and line.strip():
                text.insert("end", line.strip() + "\n", "cont")
            else:
                text.insert("end", line + "\n")

    write_marked(START)
    heading("Every command at a glance")
    text.insert("end", "\n".join(overview()) + "\n", "fixed")
    shortcuts = make_lines()
    if shortcuts:
        heading("make shortcuts")
        text.insert("end", "From the project folder (where the Makefile is). Options go as NAME=value: "
                           "make local INPUT=~/pdfs WORKERS=8\n", "note")
        text.insert("end", "\n".join(shortcuts) + "\n", "fixed")
    heading("All the options", listed="All the options:")
    text.insert("end", "Every command with all its options — each one below is the command's own --help.\n", "note")

    futures = read_all()
    pending: Dict[Command, str] = {}
    for n, command in enumerate(COMMANDS):
        heading(command.name, "cmdhead", listed=f"   {command.name}")
        also = f"{command.part} — {command.what}.   Same as: {command.python_form}"
        if command.make:
            also += f"   ·   make: {command.make}"
        text.insert("end", also + "\n", "note")
        tag = f"wait{n}"
        text.insert("end", "Reading its options…\n", ("pending", tag))
        pending[command] = tag
    text.insert("end", "\n")
    text.configure(state="disabled")

    for title, _mark in titles:
        sections.insert("end", title)

    def go_to(event=None) -> None:
        chosen = sections.curselection()
        if chosen:
            text.see("end")  # so the heading lands at the top, not just in view
            text.see(titles[chosen[0]][1])

    sections.bind("<<ListboxSelect>>", go_to)

    def fill(command: Command, ok: bool, body: str) -> None:
        tag = pending.pop(command)
        ranges = text.tag_ranges(tag)
        if not ranges:
            return
        text.configure(state="normal")
        start = ranges[0]
        text.delete(start, ranges[1])
        if ok:
            text.insert(start, body + "\n", "fixed")
        else:
            text.insert(start, f"Its options could not be read here. {body}\n"
                               f"In a terminal: {command.name} --help\n", "error")
        text.configure(state="disabled")
        if query.get().strip():
            highlight()

    def poll() -> None:
        if not win.winfo_exists():
            return
        for command in list(pending):
            future = futures[command]
            if future.done():
                try:
                    ok, body = future.result()
                except Exception as error:  # never leave a section waiting
                    ok, body = False, str(error)
                fill(command, ok, body)
        left_over = len(pending)
        status.configure(text=f"Reading the options of {left_over} command{'s' if left_over != 1 else ''}…"
                         if left_over else f"{len(COMMANDS)} commands")
        if left_over:
            win.after(100, poll)

    # Find: every match lit, Next (or Enter) goes from one to the next
    def highlight(event=None) -> int:
        text.tag_remove("found", "1.0", "end")
        text.tag_remove("current", "1.0", "end")
        words = query.get().strip()
        if not words:
            found_label.configure(text="")
            return 0
        count, start, length = 0, "1.0", tk.IntVar()
        while True:
            at = text.search(words, start, "end", nocase=True, count=length)
            if not at or not length.get():
                break
            text.tag_add("found", at, f"{at}+{length.get()}c")
            start = f"{at}+{length.get()}c"
            count += 1
        found_label.configure(text=f"{count} found" if count else "not found")
        return count

    def find_next(event=None) -> None:
        if not highlight():
            return
        current = text.tag_ranges("current")
        after = current[1] if current else text.index("@0,0")
        hit = text.tag_nextrange("found", after) or text.tag_nextrange("found", "1.0")
        text.tag_remove("current", "1.0", "end")
        text.tag_add("current", *hit)
        text.see(hit[0])

    query.trace_add("write", lambda *a: highlight())
    entry.bind("<Return>", find_next)
    next_button.configure(command=find_next)
    win.bind("<Command-f>" if sys.platform == "darwin" else "<Control-f>", lambda e: (entry.focus_set(), "break"))

    footer = ttk.Frame(win, padding=(12, 8))
    footer.pack(fill="x")

    def copy_all() -> None:
        win.clipboard_clear()
        win.clipboard_append(text.get("1.0", "end-1c"))
        status.configure(text="The whole manual is copied.")

    from LocalExtraction.gui.design import back_button
    back_button(footer, win).pack(side="right")
    ttk.Button(footer, text="Copy all", command=copy_all).pack(side="right", padx=(0, 6))
    ttk.Label(footer, foreground="#8c8c8c",
              text="Any command followed by --help prints the same in a terminal.").pack(side="left")

    from LocalExtraction.gui.design import website_line
    website_line(win)
    win.manual_text = text  # hooks for the tests
    win.manual_pending = pending
    poll()
    entry.focus_set()
    return win


def add_manual_button(parent, root):
    """The blue “Manual” button beside Requirements. `widget.open()` opens the manual (the tests use it)."""
    import tkinter as tk

    button = tk.Label(parent, text="☰ Manual", cursor="hand2", font=("TkDefaultFont", 11, "bold"), fg="white",
                      background=_BLUE, padx=12, pady=4, relief="raised", bd=1)

    def open_it(event=None):
        return open_manual(root)

    button.bind("<Button-1>", open_it)
    button.open = open_it
    from LocalExtraction.gui.theme import label_hover
    label_hover(button, lambda: _BLUE)
    return button
