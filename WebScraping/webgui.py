# WebScraping/webgui.py
"""The web side as one small chooser with two buttons — the two methods that share WebScraping/papers
and WebScraping/web_output:

  - Search open sources   method 1 (averageScrap): the existing search/review/download/extract window
  - moukhlij4scraping      method 2: collect DOIs, fetch a PDF for each, extract

Each method opens in its own window. Reached from the one project GUI (mme_gui) or on its own with
`python -m WebScraping gui`. Each time it opens it first asks for the contact e-mail and points to
the API keys and Google Chrome. tkinter is imported lazily so importing this module stays cheap."""

import os
from typing import Optional


def _window(parent):
    """A new top-level window: the application's root when there is no parent (standalone), else a
    child of the window that opened it (inside the project hub)."""
    import tkinter as tk
    return tk.Tk() if parent is None else tk.Toplevel(parent)


def open_search(parent=None):
    """Method 1 — search the open sources (the averageScrap window)."""
    from WebScraping.averageScrap.about import DEFAULT_OUTPUT, ensure_default_job
    from WebScraping.averageScrap.gui.app import App
    from WebScraping.averageScrap.job import load_env
    load_env()
    job = ensure_default_job()  # a fresh folder: start it off with the shipped job file
    win = _window(parent)
    App(win, job if os.path.exists(job) else "", DEFAULT_OUTPUT)
    return win


def open_moukhlij(parent=None):
    """Method 2 — moukhlij4scraping (fetch DOIs, scrape articles, extract)."""
    from WebScraping.moukhlij4scraping.gui import App
    win = _window(parent)
    App(win)
    return win


def open_keys(parent):
    """The API keys of both methods, one card per organization (saved in WebScraping/averageScrap/.env)."""
    from WebScraping.averageScrap.gui.dialogs import SettingsDialog
    return SettingsDialog(parent)  # saving also sets them for this session: both methods use them at once


def open_settings(parent):
    """The settings of the web search (configs/sse.yaml), used by both methods."""
    from WebScraping.averageScrap.gui.job_dialog import open_job_settings
    return open_job_settings(parent)


def open_chooser(parent=None):
    """The two-method chooser. On its own it is the root window; inside the hub it is a child."""
    import tkinter as tk
    from tkinter import ttk
    win = _window(parent)
    win.title("MoukhlijMatExtract (MME) · Web scraping")
    win.minsize(640, 300)

    frame = ttk.Frame(win, padding=24)
    frame.pack(fill="both", expand=True)
    top = ttk.Frame(frame)
    top.pack(fill="x")
    ttk.Label(top, text="Web scraping — two ways to the same database",
              font=("TkDefaultFont", 15, "bold")).pack(side="left")
    ttk.Button(top, text="API keys…", command=lambda: open_keys(win)).pack(side="right")
    ttk.Button(top, text="Search settings…", command=lambda: open_settings(win)).pack(side="right", padx=(0, 6))
    ttk.Label(frame, foreground="#8c8c8c",
              text="Both save their PDFs in WebScraping/papers/ and extract into WebScraping/web_output/.",
              ).pack(anchor="w", pady=(2, 16))

    one = ttk.LabelFrame(frame, text=" 1 · Search open sources ", padding=12)
    one.pack(fill="x")
    ttk.Label(one, foreground="#8c8c8c", wraplength=440, justify="left",
              text="Search OpenAlex, arXiv, Crossref and eleven more by keyword, keep the papers worth "
                   "reading, download the legal copies and extract them.").pack(anchor="w", pady=(0, 8))
    open_one = ttk.Button(one, text="Open", command=lambda: open_search(win))
    open_one.pack(anchor="w")

    two = ttk.LabelFrame(frame, text=" 2 · moukhlij4scraping ", padding=12)
    two.pack(fill="x", pady=(14, 0))
    ttk.Label(two, foreground="#8c8c8c", wraplength=440, justify="left",
              text="Collect the DOIs of a topic, fetch a PDF for each, then "
                   "extract them. Needs Google Chrome and this tool's own packages.").pack(anchor="w", pady=(0, 8))
    open_two = ttk.Button(two, text="Open", command=lambda: open_moukhlij(win))
    open_two.pack(anchor="w")
    ask_before_start(win, (open_one, open_two))
    return win


def ask_before_start(win, buttons):
    """The question shown each time the window opens (the e-mail, the API keys, Google Chrome). The
    buttons wait for its answer; closing it closes the window."""
    from WebScraping.averageScrap import job
    from WebScraping.averageScrap.gui.dialogs import StartDialog
    for button in buttons:
        button.state(["disabled"])

    def ready():
        for button in buttons:
            button.state(["!disabled"])
    return StartDialog(win, on_continue=ready, on_cancel=win.destroy, path=job.ENV_PATH)


def main() -> None:
    """`python -m WebScraping gui`: the chooser as a standalone window."""
    from LocalExtraction.about import enter_project_home
    from WebScraping.averageScrap.job import load_env
    enter_project_home("web", "dois")
    load_env()
    root = open_chooser(None)
    root.mainloop()
