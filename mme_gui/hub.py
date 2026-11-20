# mme_gui/hub.py
"""The hub: one root window with a button per part, and a Requirements button at the top right that
shows how to use the program and what it needs (Tesseract, the language model, …). Each part already exposes an
App(root, ...) class that uses only root-safe calls, so every part opens on a fresh Toplevel of the
hub — no second Tk(), nothing rebuilt. tkinter is imported lazily, as in every other part."""

import logging
import os
import threading
from pathlib import Path
from typing import Callable

# The Requirements button is red until the guide has been opened, then green — remembered between
# sessions in the user's home folder (per user, whatever folder they work in).
_MARKER = Path.home() / ".moukhlijmatextract" / "requirements_seen"
_RED, _GREEN = "#c62828", "#2e7d32"

# How to use the program and what it needs. "§ " heading, "• " bullet, "    - " sub-point,
# "$ " a command to type, blank line a gap.
MANUAL = """
§ What this program does
MoukhlijMatExtract reads scientific papers on solid-state electrolytes, pulls out their data
(activation energies, conductivities, diffusion coefficients, …), ranks the materials and classifies
them by structure. It has four parts; run them left to right.

§ What you need before you start
• Python 3.11 or newer (you already have it if this window is open).
• Tesseract — lets it read scanned or image-only PDFs:
    - macOS:    brew install tesseract
    - Linux:    sudo apt install tesseract-ocr
    - Windows:  installer at github.com/UB-Mannheim/tesseract/wiki
• The language model, once:
$ python -m spacy download en_core_web_sm
• API keys — all free and all optional. Set them with the “API keys…” button of the Web scraping window.
  Without any key the open sources still work; each key just opens more papers.

§ How to use it — the four steps
Steps 1 and 2 build the database; steps 3 and 4 read it. Everything is saved in the folder
MoukhlijMatExtract of your home folder (~/MoukhlijMatExtract), whatever folder you start from.

• 1 · Local extraction — put your own PDFs in  ~/MoukhlijMatExtract/LocalExtraction/papers/ , then
  open this part. It reads them into a database at  LocalExtraction/local_output/ .
• 2 · Web scraping — find papers in the open sources (OpenAlex, arXiv, Crossref and twenty-two more):
    - 1 · Fetch DOIs — collects the DOIs of the topic (OpenAlex, Crossref, Semantic Scholar, arXiv) and saves them.
    - 2 · Search — searches with the saved keywords and the saved DOIs, and proposes the papers worth
      reading; review them in the table.
    - 3 · Download — fetches the legal open-access copy of each paper kept (Unpaywall, arXiv, PubMed
      Central, …) into  WebScraping/papers/ .
    - 4 · Extract — reads them into a database at  WebScraping/web_output/ .
    - “Search settings…” changes what it looks for (searches, years, sources, words).
• 3 · Ranking — ranks the materials by activation energy: Superionic, Performant, Acceptable or
  Rejected — one ranking for each transport component (bulk, grain boundary, total), never mixed.
  Each is written to its own folder in  SelectingTopMaterial/results/ .
• 4 · Classification — sorts the materials by crystal family (NASICON, garnet, …) and by structure
  family (oxide, sulfide, halide, …), one database per class in  Classification/ .
• 5 · ML datasets — prepares a dataset for machine learning, step by step: the family, the property,
  the transport component, measured or computed, the filters, then “Generate the dataset for ML”.
  It is written into  Ready for ML/ : one row per material, every value with its sentence and page,
  what was left out and why, and a datasheet.

§ Where your files go
Everything lands in  ~/MoukhlijMatExtract , the main results folder:  LocalExtraction/ ,
WebScraping/ ,  SelectingTopMaterial/results/  and  Classification/ . The button under the title
makes it (“Create the main results folder”) and then opens it (“Open the main results folder”);
opening a part makes it too. Every table names its articles (a title column).

§ Seeing every result
• “Results…”, next to each part here, opens every table of that part: the papers, the materials,
  each transport quantity, every property, the methods, the rankings, the classes — searchable and
  sortable, with every cell of the chosen row.

§ When a step ends
• A results card appears above the tables: done, with problems, or nothing new; the numbers; the main
  findings with their articles; and buttons for the next step.
• Pause holds a running step (what is under way finishes first); Resume goes on. Stop ends it;
  the next run goes on where it stopped.
• No internet? The step says so and waits for the connection to come back, then goes on by itself.
• Work already done is skipped and said so (“Already extracted”, “Already ranked”, …): running a part
  again only does what is new.
• “Delete outputs…”, next to each part here and in each window, starts a part over. The files go to
  the Trash; your own PDFs, the search settings and the API keys are never deleted.

§ Good to know
• This button is red until you have opened this guide, then it turns green. You can reopen it any time.
• The blue “Manual” button beside it lists every command, with all its options, to run each part
  from a terminal (mme-local, mme-web, mme-rank, …) — and the make shortcuts.
• Web scraping fetches legal open-access copies only, and follows each site's robots.txt.
• The website shows how to use the program step by step and gives an overview of the project:
  its address is at the bottom of every window, and a click opens it.
"""


def requirements_seen() -> bool:
    """True once the user has opened the Requirements guide at least once."""
    try:
        return _MARKER.exists()
    except OSError:
        return False


def mark_requirements_seen() -> None:
    try:
        _MARKER.parent.mkdir(parents=True, exist_ok=True)
        _MARKER.touch()
    except OSError:
        pass  # a read-only home must not stop the program


def _toplevel(root):
    import tkinter as tk
    return tk.Toplevel(root)


def open_requirements(parent) -> "object":
    """The manual and the requirements, in a scrollable read-only window."""
    import tkinter as tk
    from tkinter import ttk

    win = _toplevel(parent)
    win.title("MoukhlijMatExtract · Requirements & how to use it")
    from LocalExtraction.gui import layout
    layout.place(win, (780, 640), (620, 460), parent=parent)
    try:
        win.transient(parent.winfo_toplevel())
    except Exception:
        pass
    win.bind("<Escape>", lambda event: win.destroy())

    body = ttk.Frame(win)
    body.pack(fill="both", expand=True)
    text = tk.Text(body, wrap="word", padx=18, pady=12, relief="flat", font=("TkDefaultFont", 11),
                   cursor="arrow", background="white", foreground="#222222")
    bar = ttk.Scrollbar(body, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=bar.set)
    text.tag_configure("h", font=("TkDefaultFont", 14, "bold"), foreground="#143a5c", spacing1=14, spacing3=5)
    text.tag_configure("bullet", lmargin1=18, lmargin2=34, spacing3=2)
    text.tag_configure("sub", lmargin1=42, lmargin2=58, foreground="#444444", spacing3=2)
    from .manual import mono
    text.tag_configure("cmd", font=mono(11), foreground="#8a3b00", lmargin1=34, lmargin2=34, spacing1=2, spacing3=4)
    for line in MANUAL.strip("\n").splitlines():
        if line.startswith("§ "):
            text.insert("end", line[2:] + "\n", "h")
        elif line.startswith("$ "):
            text.insert("end", line[2:] + "\n", "cmd")
        elif line.startswith("    - "):
            text.insert("end", "– " + line[6:] + "\n", "sub")
        elif line.startswith("• "):
            text.insert("end", "• " + line[2:] + "\n", "bullet")
        else:
            text.insert("end", line + "\n")
    text.configure(state="disabled")
    text.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")

    footer = ttk.Frame(win, padding=(12, 8))
    footer.pack(fill="x")
    ttk.Button(footer, text="Close", command=win.destroy).pack(side="right")
    from LocalExtraction.gui.design import website_line
    website_line(win)
    return win


def add_requirements_button(parent, root):
    """A red “Requirements” button that turns green once the guide has been opened. Returns the
    widget; `widget.open()` opens the guide (used by the window and by the tests)."""
    import tkinter as tk

    button = tk.Label(parent, cursor="hand2", font=("TkDefaultFont", 11, "bold"), fg="white",
                      padx=12, pady=4, relief="raised", bd=1)

    def refresh() -> None:
        seen = requirements_seen()
        button.configure(text="✓ Requirements" if seen else "⚠ Requirements", background=_GREEN if seen else _RED)

    def open_guide(event=None) -> None:
        open_requirements(root)
        mark_requirements_seen()
        refresh()

    button.bind("<Button-1>", open_guide)
    button.open = open_guide  # a hook for the tests
    from LocalExtraction.gui.theme import label_hover
    label_hover(button, lambda: _GREEN if requirements_seen() else _RED)
    refresh()
    return button


def open_local(root) -> None:
    from LocalExtraction.gui.app import App
    App(_toplevel(root))


def open_web(root) -> None:
    from WebScraping.webgui import open_web as open_window
    open_window(root)


def open_rank(root) -> None:
    from SelectingTopMaterial.gui import App
    App(_toplevel(root))


def open_ml(root) -> None:
    from MLDataset.gui import MLWindow
    MLWindow(_toplevel(root))


def open_classify(root) -> None:
    from Classification.gui import App
    App(_toplevel(root))


# (button text, one-line description, what it opens, its key in LocalExtraction.outputs.PARTS)
PARTS = (
    ("1 · Local extraction", "Your own PDFs (~/MoukhlijMatExtract/LocalExtraction/papers/) into a database.",
     open_local, "local"),
    ("2 · Web scraping", "Search the open sources, download the legal copies and extract them.", open_web, "web"),
    ("3 · Ranking", "Rank the materials by activation energy.", open_rank, "rank"),
    ("4 · Classification", "Sort the materials by crystal family and structure family.", open_classify, "classify"),
    ("5 · ML datasets", "Filter the data and prepare datasets for machine learning (Ready for ML/).", open_ml, "ml"),
)


def open_delete(root, part: str) -> None:
    """The "Delete outputs…" dialog of one part."""
    from LocalExtraction.gui.delete_outputs import DeleteOutputsDialog
    DeleteOutputsDialog(root, part)


def home_ready() -> "Path":
    """Makes the main results folder (~/MoukhlijMatExtract), every part's folders, its configs/ (the job files that
    are missing) and its docs/ (the documents), and works from there. A part needs them before it opens."""
    from LocalExtraction.about import PART_FOLDERS, enter_project_home
    from WebScraping.averageScrap.about import ensure_default_job
    home = enter_project_home(*PART_FOLDERS)  # configs/ and docs/ too (mme_home.populate)
    ensure_default_job()
    return home


_WARN, _OK = "#d97706", "#2e9e5b"


def _shown_home() -> str:
    from LocalExtraction.about import PROJECT_HOME
    try:
        return "~/" + str(PROJECT_HOME.relative_to(Path.home()))
    except ValueError:
        return str(PROJECT_HOME)


def home_problem() -> "tuple[str, str]":
    """What the main results folder lacks: ("missing" | "configs" | "docs" | "", what to tell the user)."""
    import mme_home
    from LocalExtraction.about import PROJECT_HOME
    state, shown = mme_home.status(PROJECT_HOME), _shown_home()
    jobs, documents = len(mme_home.shipped(mme_home.CONFIGS)), len(mme_home.shipped(mme_home.DOCS))
    if not state["home"]:
        return "missing", (f"{shown} does not exist: it holds your PDFs, the results, the {jobs} job files of the web "
                           f"search (configs/) and the {documents} documents (docs/). Create it to start.")
    missing = state[mme_home.CONFIGS]
    if missing:
        names = ", ".join(missing[:4]) + ("…" if len(missing) > 4 else "")
        return "configs", (f"{len(missing)} of the {jobs} job files are missing from {shown}/configs ({names}): the web "
                           "scraping needs them. Press “Restore the job files” to make them again.")
    if state[mme_home.DOCS]:
        return "docs", (f"{len(state[mme_home.DOCS])} of the {documents} documents are missing from {shown}/docs. "
                        "Press “Restore the job files” to make them again.")
    return "", f"✓ {jobs} job files in configs/ · {documents} documents in docs/"


def restore(root) -> bool:
    """Makes the main results folder when it is missing, and every job file and document that is missing (a job file
    the user edited is never written over). Says what was made. Returns whether all is there now."""
    from tkinter import messagebox

    import mme_home
    from LocalExtraction.about import PROJECT_HOME
    existed = PROJECT_HOME.is_dir()
    try:
        written = mme_home.populate(PROJECT_HOME) if existed else []
        home_ready()
    except OSError as error:
        messagebox.showerror("MoukhlijMatExtract", f"The folder could not be made:\n{error}", parent=root)
        return False
    if not existed:
        written = list((PROJECT_HOME / mme_home.CONFIGS).glob("*.yaml")) + list((PROJECT_HOME / mme_home.DOCS).glob("*.md"))
    jobs = sorted(p.name for p in written if p.suffix == ".yaml")
    documents = sorted(p.name for p in written if p.suffix == ".md")
    shown = _shown_home()
    if not existed:
        message = (f"Made {shown}, with a folder for each part:\n\n"
                   "LocalExtraction/papers — put your own PDFs here\nLocalExtraction/local_output\n"
                   "WebScraping/papers, web_output\nSelectingTopMaterial/results\n"
                   "Classification/crystal_structure, structure_families\n"
                   f"configs — the {len(jobs)} job files of the web search: {', '.join(jobs)}\n"
                   f"docs — the {len(documents)} documents: {', '.join(documents)}")
    elif written:
        message = (f"Made again in {shown}:\n\n"
                   + (f"configs/ — {len(jobs)} job file(s): {', '.join(jobs)}\n" if jobs else "")
                   + (f"docs/ — {len(documents)} document(s): {', '.join(documents)}\n" if documents else "")
                   + "\nThe job files you edited were kept as they are.")
    else:
        message = (f"Everything is there already in {shown}: every job file in configs/ and every document in docs/. "
                   "(A job file you edited is never written over.)")
    messagebox.showinfo("MoukhlijMatExtract", message, parent=root)
    return not home_problem()[0]


def folder_button(parent, root):
    """The main results folder, ~/MoukhlijMatExtract, which holds the folders of every part, the job files (configs/)
    and the documents (docs/): "Create the main results folder" while it does not exist, then "Open the main results
    folder"; "Restore the job files" makes again whatever is missing; "Open the documents". The line under them
    says what is missing, if anything. It looks again each time the hub comes to the front (the folder may have been
    deleted)."""
    from tkinter import ttk

    from LocalExtraction.about import PROJECT_HOME
    from LocalExtraction.gui import widgets
    from LocalExtraction.gui.widgets import WrapLabel

    row = ttk.Frame(parent)
    status = WrapLabel(row, justify="left", font=("TkDefaultFont", 11, "bold"))
    status.pack(side="bottom", fill="x", pady=(6, 0))
    button = ttk.Button(row)
    button.pack(side="left")
    restore_button = ttk.Button(row, text="Restore the job files", command=lambda: (restore(root), refresh()))
    restore_button.pack(side="left", padx=(6, 0))
    docs_button = ttk.Button(row, text="Open the documents", command=lambda: open_documents())
    docs_button.pack(side="left", padx=(6, 0))
    where = WrapLabel(row, foreground="#8c8c8c", justify="left")
    where.pack(side="left", padx=10, fill="x", expand=True)
    shown = _shown_home()

    def refresh(event=None) -> None:
        exists = PROJECT_HOME.is_dir()
        button.configure(text="Open the main results folder" if exists else "Create the main results folder")
        where.configure(text=f"{shown} — every part's PDFs, databases, results, job files and documents"
                        if exists else f"{shown} does not exist yet")
        level, text = home_problem()
        status.configure(text=("⚠ " + text) if level else text, foreground=_WARN if level else _OK)

    def press() -> None:
        if PROJECT_HOME.is_dir():
            widgets.open_path(str(PROJECT_HOME))
        else:
            restore(root)
        refresh()

    def open_documents() -> None:
        import mme_home
        documents = PROJECT_HOME / mme_home.DOCS
        if not documents.is_dir() or home_problem()[0] in ("missing", "docs"):
            if not restore(root):
                refresh()
                return
        widgets.open_path(str(documents))
        refresh()

    button.configure(command=press)
    refresh()
    root.bind("<FocusIn>", lambda event: refresh() if event.widget is root else None, add="+")
    row.refresh = refresh  # the hub refreshes it after opening a part (which makes the folder)
    return row


def warn_if_missing(root) -> None:
    """At the start of the main window: when the main results folder or its job files are missing (a fresh
    computer, or a folder deleted), a small window says so and offers to make them now."""
    from tkinter import messagebox
    level, text = home_problem()
    if level not in ("missing", "configs"):
        return
    question = "Create it now?" if level == "missing" else "Make the missing job files again now?"
    if messagebox.askyesno("MoukhlijMatExtract", f"{text}\n\n{question}", icon="warning", parent=root):
        restore(root)
    refresh = getattr(root, "_mme_folder_refresh", None)
    if refresh is not None:
        refresh()


def open_results(root, part: str) -> None:
    """Every result of a part, table by table."""
    from LocalExtraction.gui.browser import open_results as browse
    browse(root, part)


def _open(root, opener: Callable, make_home: bool = True, what: str = "This part") -> None:
    """Opens a part. When the main results folder or its job files are missing, a small window says so first and
    asks to make them: a part works in that folder (the web scraping with its job files); “No” leaves it closed."""
    from tkinter import messagebox
    try:
        if make_home:
            level, text = home_problem()
            if level in ("missing", "configs"):
                question = (f"{what} needs it: create it now, with every job file and document?" if level == "missing"
                            else f"{what} needs them: make the missing job files again now?")
                if not messagebox.askyesno("MoukhlijMatExtract", f"{text}\n\n{question}", icon="warning", parent=root):
                    return
            home_ready()
        opener(root)
    except Exception as error:  # one part failing to open must not take the hub down
        logging.getLogger(__name__).exception("Could not open a part from the hub")
        messagebox.showerror("MoukhlijMatExtract",
                             f"This part could not be opened:\n{type(error).__name__}: {error}", parent=root)
    refresh = getattr(root, "_mme_folder_refresh", None)
    if refresh is not None:
        refresh()


def part_status(part: str) -> str:
    """What a part's results folder holds now, in a few words ("database: 647 papers"); "" when nothing yet."""
    from LocalExtraction.gui.browser import part_tables

    def rows(path) -> int:
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                return max(0, sum(1 for _ in f) - 1)
        except OSError:
            return 0
    try:
        _, folder, _ = part_tables(part)
    except ValueError:
        return ""
    if part in ("local", "web"):
        papers = rows(folder / "papers.csv")
        values = rows(folder / "activation_energy.csv")
        if not papers:
            return "no database yet"
        from LocalExtraction.verification import Verifications
        checked = len(Verifications.of(folder, folder.parents[1]))  # ~/MoukhlijMatExtract/Verification/<database>.csv
        return (f"database: {papers:,} papers, {values:,} activation energies · {checked:,} checked by hand"
                + (f" ({100 * checked / values:.0f} %)" if values and checked else ""))
    if part == "rank":
        summary = folder / "summary.csv"
        if summary.is_file():
            import time
            return "last ranking: " + time.strftime("%d %b %Y %H:%M", time.localtime(summary.stat().st_mtime))
        return "no ranking written yet"
    if part == "ml":
        made = [p for p in folder.iterdir() if (p / "dataset.csv").is_file()] if folder.is_dir() else []
        return f"{len(made)} dataset(s) in Ready for ML/" if made else "no dataset prepared yet"
    every = folder / "all_materials.csv"
    return f"classes written for {rows(every):,} materials" if every.is_file() else "no classes written yet"


def build(root):
    """Builds the hub on `root`. Returns the Requirements button (the tests look at it)."""
    import tkinter as tk
    from tkinter import ttk

    from LocalExtraction.gui import design, theme
    from LocalExtraction.gui.widgets import WrapLabel
    theme.apply(root)  # buttons that light up under the mouse
    root.title("MoukhlijMatExtract (MME)")
    colours = theme.palette(root)

    band = design.header(root, "MoukhlijMatExtract (MME)",
                  "Battery-materials data from the scientific literature: search, legal retrieval, extraction, "
                  "ranking and classification", kicker="Literature mining for solid electrolytes, cathodes and anodes")
    root._mme_band = band  # the announcement of the website opens under it
    from LocalExtraction.gui.widgets import Scrolled
    body = Scrolled(root)  # a screen too short for it all: the rest is a scroll away, never cut off
    body.pack(fill="both", expand=True)
    frame = ttk.Frame(body.inner, padding=(24, 14, 24, 18))
    frame.pack(fill="both", expand=True)

    top = ttk.Frame(frame)
    top.pack(fill="x")
    ttk.Label(top, text="The pipeline", style="Section.TLabel").pack(side="left")
    requirements = add_requirements_button(top, root)
    requirements.pack(side="right")
    from .manual import add_manual_button  # every command and its options
    root._mme_manual = add_manual_button(top, root)
    root._mme_manual.pack(side="right", padx=(0, 8))

    def about() -> None:
        from LocalExtraction.gui.about_window import open_about
        open_about(root)
    ttk.Button(top, text="About & methods", command=about).pack(side="right", padx=(0, 8))
    # One switch for every window: a long search or download is not stopped by the computer going to sleep.
    design.keep_awake_switch(top).pack(side="right", padx=(0, 14))

    ttk.Label(frame, style="Muted.TLabel",
              text="Pick a step. Each opens in its own window; the pipeline runs left to right — "
                   "1 or 2 build the database, 3 and 4 read it.").pack(anchor="w", pady=(4, 10))
    folder = folder_button(frame, root)
    folder.pack(fill="x", pady=(0, 12))

    statuses = []
    wrapping = []  # the labels that wrap: the height the hub needs follows them
    for label, description, opener, part in PARTS:
        card = ttk.Frame(frame, padding=(0, 0, 12, 0), relief="solid", borderwidth=1)
        card.pack(fill="x", pady=4)
        tk.Frame(card, background=colours["garnet"], width=4).pack(side="left", fill="y")
        inner = ttk.Frame(card, padding=(12, 9, 0, 9))
        inner.pack(side="left", fill="x", expand=True)
        ttk.Button(inner, text=label, width=22,
                   command=lambda o=opener, n=label: _open(root, o, what=n.split(" · ", 1)[-1])).pack(side="left")
        ttk.Button(inner, text="Delete outputs…",
                   command=lambda p=part: _open(root, lambda r: open_delete(r, p), make_home=False)).pack(side="right")
        ttk.Button(inner, text="Results…",
                   command=lambda p=part: _open(root, lambda r: open_results(r, p), make_home=False)).pack(side="right",
                                                                                                         padx=(0, 6))
        texts = ttk.Frame(inner)
        texts.pack(side="left", padx=14, fill="x", expand=True)
        said = WrapLabel(texts, text=description, wraplength=360)  # wraps to the room it has
        said.pack(fill="x", anchor="w")
        status = WrapLabel(texts, style="Muted.TLabel", font=("TkDefaultFont", 10), wraplength=360)
        status.pack(fill="x", anchor="w")
        wrapping += [said, status]
        statuses.append((part, status))

    def refresh(event=None) -> None:
        folder.refresh()
        for part, status in statuses:
            status.configure(text=part_status(part))
    root._mme_folder_refresh = refresh
    refresh()
    root.bind("<FocusIn>", lambda event: refresh() if event.widget is root else None, add="+")  # a part ran meanwhile

    about_footer(frame).pack(side="bottom", fill="x", pady=(18, 0))
    # It opens as tall as all it holds (the cards and the footer, whatever the fonts), as far as the screen allows,
    # centred; it can be made smaller, the rest then scrolls. The descriptions wrap once it is shown: it grows with
    # them until a person resizes it.
    from LocalExtraction.gui import layout

    def wanted() -> int:
        return band.winfo_reqheight() + frame.winfo_reqheight() + 2

    root.update_idletasks()
    layout.place(root, (max(820, frame.winfo_reqwidth()), wanted()), (820, 560))
    sized = {"by_us": int(root.geometry().split("x")[1].split("+")[0]), "by_hand": False}  # the height it opens at

    def fit_height() -> None:
        try:
            height = min(wanted(), layout.usable(root)[1])
            if not sized["by_hand"] and root.winfo_ismapped() and root.winfo_height() < height:
                sized["by_us"] = height
                root.geometry(f"{root.winfo_width()}x{height}")
        except tk.TclError:  # the window is closing
            pass

    def resized(event) -> None:
        if event.widget is root and event.height not in (sized["by_us"], 1):
            sized["by_hand"] = True  # a person chose its size: left as it is

    root.bind("<Configure>", resized, add="+")
    for label in wrapping:
        label.bind("<Configure>", lambda event: root.after_idle(fit_height), add="+")
    return requirements


def about_footer(parent):
    """The bottom of the hub: what the project is, who made it, and where to find them."""
    import tkinter as tk
    import webbrowser
    from tkinter import ttk

    from LocalExtraction.about import (ABOUT_AUTHOR, ABOUT_PROJECT, CITE_TEXT, CONTACT_EMAIL, FULL_NAME,
                                       LICENSE_NAME, REPOSITORY, WEBSITE, version)

    footer = ttk.Frame(parent)
    ttk.Separator(footer).pack(fill="x", pady=(0, 12))
    columns = ttk.Frame(footer)
    columns.pack(fill="x")
    for column, (heading, text) in enumerate((("About the project", ABOUT_PROJECT),
                                              ("About the author", ABOUT_AUTHOR))):
        block = ttk.Frame(columns)
        block.grid(row=0, column=column, sticky="nw", padx=(0, 24) if column == 0 else 0)
        columns.columnconfigure(column, weight=1, uniform="about")
        ttk.Label(block, text=heading, font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        text_label = ttk.Label(block, text=text, justify="left", wraplength=340)
        text_label.pack(anchor="w", pady=(4, 0))
        # The text follows the width of its column when the window is resized.
        block.bind("<Configure>", lambda event, label=text_label: label.configure(wraplength=max(200, event.width)))

    ttk.Label(footer, text=CITE_TEXT, foreground="#888888", font=("TkDefaultFont", 9)).pack(anchor="w", pady=(12, 0))
    line = ttk.Frame(footer)
    line.pack(fill="x", pady=(4, 0))
    number = version()
    ttk.Label(line, foreground="#888888", font=("TkDefaultFont", 9),
              text=f"{FULL_NAME}{f' v{number}' if number else ''} · {LICENSE_NAME} · ").pack(side="left")
    from LocalExtraction.gui.design import website_address
    links = ((f"Website: {website_address()} ↗", WEBSITE), ("GitHub ↗", REPOSITORY),
             (CONTACT_EMAIL, f"mailto:{CONTACT_EMAIL}"))
    for index, (label, target) in enumerate(links):
        if index:
            ttk.Label(line, text=" · ", foreground="#888888", font=("TkDefaultFont", 9)).pack(side="left")
        link = tk.Label(line, text=label, fg="#4a90d9", cursor="hand2", font=("TkDefaultFont", 9, "underline"),
                        bg=ttk.Style().lookup("TFrame", "background") or None)
        link.pack(side="left")
        link.bind("<Button-1>", lambda event, url=target: webbrowser.open(url))
    return footer


# How long the announcement of the website stays on the main window, unless closed sooner.
ANNOUNCEMENT_SECONDS = 7


def announce_website(root, seconds: int = ANNOUNCEMENT_SECONDS):
    """A card over the top of the main window, each time it opens: the project has a website, to learn how to use
    the program and to get an overview of the project, with its link. It closes by itself after `seconds`, or at
    once with its ✕. Drawn inside the window (not a window of its own): it never takes the focus nor outlives the
    hub. Returns the card; `card.close()` closes it."""
    import tkinter as tk

    from LocalExtraction.gui import design, theme
    colours = theme.palette(root)
    paper = colours["card"]
    card = tk.Frame(root, background=paper, highlightthickness=1, highlightbackground=colours["line"],
                    highlightcolor=colours["line"])
    tk.Frame(card, background=colours["garnet"], width=5).pack(side="left", fill="y")
    inner = tk.Frame(card, background=paper, padx=16, pady=12)
    inner.pack(side="left", fill="both", expand=True)
    head = tk.Frame(inner, background=paper)
    head.pack(fill="x")
    tk.Label(head, text="New: the MoukhlijMatExtract website", background=paper, foreground=colours["ink"],
             font=("TkDefaultFont", 13, "bold")).pack(side="left")
    cross = tk.Label(head, text="✕", background=paper, foreground=colours["muted"], cursor="hand2",
                     font=("TkDefaultFont", 13), padx=4)
    cross.pack(side="right", anchor="n", padx=(16, 0))
    tk.Label(inner, background=paper, foreground=colours["ink"], justify="left", wraplength=420,
             text="Learn how to use the program, step by step, and get an overview of the project.").pack(
        anchor="w", pady=(6, 8))
    design.website_link(inner, size=12, background=paper).pack(anchor="w")
    tk.Label(inner, text=f"Closes by itself in {seconds} s · the link stays at the bottom of every window.",
             background=paper, foreground=colours["muted"], font=("TkDefaultFont", 9)).pack(anchor="w", pady=(8, 0))

    timer = []

    def close(event=None) -> None:
        for job in timer:
            try:
                root.after_cancel(job)
            except tk.TclError:
                pass
        timer.clear()
        if card.winfo_exists():
            card.destroy()

    cross.bind("<Button-1>", close)
    cross.bind("<Enter>", lambda event: cross.configure(foreground=colours["ink"]))
    cross.bind("<Leave>", lambda event: cross.configure(foreground=colours["muted"]))
    card.close, card.cross = close, cross  # hooks for the tests

    band = getattr(root, "_mme_band", None)
    root.update_idletasks()
    top = (band.winfo_height() + 3 if band is not None and band.winfo_exists() else 0) + 14
    card.place(relx=0.5, y=top, anchor="n")
    card.lift()
    timer.append(root.after(int(seconds * 1000), close))
    root._mme_announcement = card
    return card


# What the windows of the parts need, loaded behind the hub while it is read: pandas and each part's
# code take about a second, which would otherwise freeze the first window opened. Not the PDF reader
# nor the language model: an extraction loads them on its own thread.
WARM_UP = ("pandas", "LocalExtraction.gui.app", "LocalExtraction.gui.browser", "WebScraping.webgui",
           "WebScraping.averageScrap.gui.app", "SelectingTopMaterial.gui", "Classification.gui")


def warm_up() -> threading.Thread:
    import importlib

    def load() -> None:
        for name in WARM_UP:
            try:
                importlib.import_module(name)
            except Exception:  # the window says what is wrong when it is opened
                logging.getLogger(__name__).debug("Could not load %s ahead", name, exc_info=True)
    worker = threading.Thread(target=load, name="mme-warm-up", daemon=True)
    worker.start()
    return worker


def main(argv=None) -> None:
    import argparse

    from LocalExtraction.about import PROJECT_HOME, require_tk, version_text
    parser = argparse.ArgumentParser(
        prog="mme-gui", description="Open the MoukhlijMatExtract window: one button per part.")
    parser.add_argument("--version", action="version", version=version_text("mme-gui"))
    parser.parse_args(argv)
    require_tk("mme-gui")
    import tkinter as tk
    # The main results folder is not made here: "Create the main results folder" makes it, or the
    # first part opened. When it is there, the hub works from it.
    if PROJECT_HOME.is_dir():
        os.chdir(PROJECT_HOME)
    root = tk.Tk()
    from LocalExtraction import crashlog
    crashlog.install("mme-gui")  # the hub does not enter the main folder: installed here
    crashlog.watch(root)  # every part opens on a Toplevel of this root: one place for their errors
    build(root)
    root.after(300, lambda: announce_website(root))  # the website: how to use it, an overview (7 s, or its ✕)
    root.after(600, lambda: warn_if_missing(root))  # the folder or its job files missing: said, and offered to be made
    warm_up()
    from LocalExtraction.crashlog import run
    run(root)  # the loop, then the window closed cleanly


if __name__ == "__main__":
    main()
