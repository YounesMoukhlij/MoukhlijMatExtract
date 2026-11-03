# mme_gui/hub.py
"""The hub: one root window with a button per part, and a Requirements button at the top right that
shows how to use the program and what it needs (Chrome, Tesseract, …). Each part already exposes an
App(root, ...) class that uses only root-safe calls, so every part opens on a fresh Toplevel of the
hub — no second Tk(), nothing rebuilt. tkinter is imported lazily, as in every other part."""

import logging
import os
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
• Google Chrome — only for web method 2 (moukhlij4scraping), which fetches a PDF for each DOI.
• The extra packages for that method, once:
$ pip install "moukhlijmatextract[scrape]"
• API keys — all free and all optional. Set them with the “API keys…” button inside the web windows.
  Without any key the open sources still work; each key just opens more papers.

§ How to use it — the four steps
Steps 1 and 2 build the database; steps 3 and 4 read it. Everything is saved in the folder
MoukhlijMatExtract of your home folder (~/MoukhlijMatExtract), whatever folder you start from.

• 1 · Local extraction — put your own PDFs in  ~/MoukhlijMatExtract/LocalExtraction/papers/ , then
  open this part. It reads them into a database at  LocalExtraction/local_output/ .
• 2 · Web scraping — find papers online. Two methods, one database:
    - Search open sources — search by keywords, download the legal copies, extract them.
    - moukhlij4scraping — collect DOIs (you choose how many), fetch a PDF for each, then extract.
      “Fetched DOIs (N)…” shows the list and where each DOI stands. “Scrape articles” asks how many
      DOIs to try and whether to start with the legal open-access copies.
    - “Search settings…” changes what both methods look for (searches, years, sources, words).
• 3 · Ranking — ranks the materials by activation energy: Superionic, Performant, Acceptable or
  Rejected — one ranking for each transport component (bulk, grain boundary, total), never mixed.
  Each is written to its own folder in  SelectingTopMaterial/results/ .
• 4 · Classification — sorts the materials by crystal family (NASICON, garnet, …) and by structure
  family (oxide, sulfide, halide, …), one database per class in  Classification/ .

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
• Work already done is skipped and said so (“Already extracted”, “Already ranked”, …): running a part
  again only does what is new.
• “Delete outputs…”, next to each part here and in each window, starts a part over. The files go to
  the Trash; your own PDFs, the search settings and the API keys are never deleted.

§ Good to know
• This button is red until you have opened this guide, then it turns green. You can reopen it any time.
• The web method 2 (moukhlij4scraping) does not only fetch open-access copies — check your
  institution's rules; it is meant for academic literature research.
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
    win.geometry("780x640")
    win.minsize(620, 460)
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
    text.tag_configure("cmd", font=("TkFixedFont", 11), foreground="#8a3b00", lmargin1=34, lmargin2=34, spacing1=2, spacing3=4)
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
    refresh()
    return button


def open_local(root) -> None:
    from LocalExtraction.gui.app import App
    App(_toplevel(root))


def open_web(root) -> None:
    # The web side is itself two methods, so it opens its own chooser (a child of the hub).
    from WebScraping.webgui import open_chooser
    open_chooser(root)


def open_rank(root) -> None:
    from SelectingTopMaterial.gui import App
    App(_toplevel(root))


def open_classify(root) -> None:
    from Classification.gui import App
    App(_toplevel(root))


# (button text, one-line description, what it opens, its key in LocalExtraction.outputs.PARTS)
PARTS = (
    ("1 · Local extraction", "Your own PDFs (~/MoukhlijMatExtract/LocalExtraction/papers/) into a database.",
     open_local, "local"),
    ("2 · Web scraping", "Find papers online and extract them — two methods, one database.", open_web, "web"),
    ("3 · Ranking", "Rank the materials by activation energy.", open_rank, "rank"),
    ("4 · Classification", "Sort the materials by crystal family and structure family.", open_classify, "classify"),
)


def open_delete(root, part: str) -> None:
    """The "Delete outputs…" dialog of one part."""
    from LocalExtraction.gui.delete_outputs import DeleteOutputsDialog
    DeleteOutputsDialog(root, part)


def home_ready() -> "Path":
    """Makes the main results folder (~/MoukhlijMatExtract) and every part's folders when missing,
    and works from there. A part needs them before it opens."""
    from LocalExtraction.about import PART_FOLDERS, enter_project_home
    return enter_project_home(*PART_FOLDERS)


def folder_button(parent, root):
    """The button of the main results folder, ~/MoukhlijMatExtract, which holds the folders of every
    part: "Create the main results folder" while it does not exist, then "Open the main results
    folder". It looks again each time the hub comes to the front (the folder may have been deleted)."""
    from tkinter import messagebox, ttk

    from LocalExtraction.about import PROJECT_HOME
    from LocalExtraction.gui import widgets
    from LocalExtraction.gui.widgets import WrapLabel

    row = ttk.Frame(parent)
    button = ttk.Button(row)
    button.pack(side="left")
    where = WrapLabel(row, foreground="#8c8c8c", justify="left")
    where.pack(side="left", padx=10, fill="x", expand=True)
    try:
        shown = "~/" + str(PROJECT_HOME.relative_to(Path.home()))
    except ValueError:
        shown = str(PROJECT_HOME)

    def refresh(event=None) -> None:
        exists = PROJECT_HOME.is_dir()
        button.configure(text="Open the main results folder" if exists else "Create the main results folder")
        where.configure(text=f"{shown} — every part's PDFs, databases and results are kept here"
                        if exists else f"{shown} does not exist yet: it is made here, or when a part first opens")

    def press() -> None:
        if PROJECT_HOME.is_dir():
            widgets.open_path(str(PROJECT_HOME))
        else:
            try:
                home_ready()
            except OSError as error:
                messagebox.showerror("MoukhlijMatExtract", f"The folder could not be made:\n{error}", parent=root)
                return
            messagebox.showinfo("MoukhlijMatExtract", f"Made {PROJECT_HOME}, with a folder for each part:\n\n"
                                "LocalExtraction/papers — put your own PDFs here\nLocalExtraction/local_output\n"
                                "WebScraping/papers, web_output, Fetch_DOIs\nSelectingTopMaterial/results\n"
                                "Classification/crystal_structure, structure_families", parent=root)
        refresh()

    button.configure(command=press)
    refresh()
    root.bind("<FocusIn>", lambda event: refresh() if event.widget is root else None, add="+")
    row.refresh = refresh  # the hub refreshes it after opening a part (which makes the folder)
    return row


def open_results(root, part: str) -> None:
    """Every result of a part, table by table."""
    from LocalExtraction.gui.browser import open_results as browse
    browse(root, part)


def _open(root, opener: Callable, make_home: bool = True) -> None:
    from tkinter import messagebox
    try:
        if make_home:
            home_ready()
        opener(root)
    except Exception as error:  # one part failing to open must not take the hub down
        logging.getLogger(__name__).exception("Could not open a part from the hub")
        messagebox.showerror("MoukhlijMatExtract",
                             f"This part could not be opened:\n{type(error).__name__}: {error}", parent=root)
    refresh = getattr(root, "_mme_folder_refresh", None)
    if refresh is not None:
        refresh()


def build(root):
    """Builds the hub on `root`. Returns the Requirements button (the tests look at it)."""
    import tkinter as tk
    from tkinter import ttk

    root.title("MoukhlijMatExtract (MME)")
    root.minsize(780, 500)

    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)

    top = ttk.Frame(frame)
    top.pack(fill="x")
    ttk.Label(top, text="MoukhlijMatExtract", font=("TkDefaultFont", 18, "bold")).pack(side="left")
    requirements = add_requirements_button(top, root)
    requirements.pack(side="right")

    ttk.Label(frame, foreground="#8c8c8c",
              text="Pick a step. Each opens in its own window; the pipeline runs left to right — "
                   "1 or 2 build the database, 3 and 4 read it.").pack(anchor="w", pady=(6, 10))
    folder = folder_button(frame, root)
    folder.pack(fill="x", pady=(0, 14))
    root._mme_folder_refresh = folder.refresh

    for label, description, opener, part in PARTS:
        card = ttk.Frame(frame)
        card.pack(fill="x", pady=5)
        ttk.Button(card, text=label, width=22, command=lambda o=opener: _open(root, o)).pack(side="left")
        ttk.Button(card, text="Delete outputs…",
                   command=lambda p=part: _open(root, lambda r: open_delete(r, p), make_home=False)).pack(side="right")
        ttk.Button(card, text="Results…",
                   command=lambda p=part: _open(root, lambda r: open_results(r, p), make_home=False)).pack(side="right",
                                                                                                         padx=(0, 6))
        ttk.Label(card, foreground="#8c8c8c", text=description, wraplength=320,
                  justify="left").pack(side="left", padx=12)

    about_footer(frame).pack(side="bottom", fill="x", pady=(20, 0))
    return requirements


def about_footer(parent):
    """The bottom of the hub: what the project is, who made it, and where to find them."""
    import tkinter as tk
    import webbrowser
    from tkinter import ttk

    from LocalExtraction.about import (ABOUT_AUTHOR, ABOUT_PROJECT, CITE_TEXT, CONTACT_EMAIL, FULL_NAME,
                                       LICENSE_NAME, REPOSITORY, version)

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
    for index, (label, target) in enumerate((("GitHub ↗", REPOSITORY), (CONTACT_EMAIL, f"mailto:{CONTACT_EMAIL}"))):
        if index:
            ttk.Label(line, text=" · ", foreground="#888888", font=("TkDefaultFont", 9)).pack(side="left")
        link = tk.Label(line, text=label, fg="#4a90d9", cursor="hand2", font=("TkDefaultFont", 9, "underline"),
                        bg=ttk.Style().lookup("TFrame", "background") or None)
        link.pack(side="left")
        link.bind("<Button-1>", lambda event, url=target: webbrowser.open(url))
    return footer


def main(argv=None) -> None:
    import argparse
    import tkinter as tk

    from LocalExtraction.about import PROJECT_HOME, version
    parser = argparse.ArgumentParser(
        prog="mme-gui", description="Open the MoukhlijMatExtract window: one button per part.")
    parser.add_argument("--version", action="version", version=f"MoukhlijMatExtract {version()}")
    parser.parse_args(argv)
    # The main results folder is not made here: "Create the main results folder" makes it, or the
    # first part opened. When it is there, the hub works from it.
    if PROJECT_HOME.is_dir():
        os.chdir(PROJECT_HOME)
    root = tk.Tk()
    build(root)
    root.mainloop()


if __name__ == "__main__":
    main()
