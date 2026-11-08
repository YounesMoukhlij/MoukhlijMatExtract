# WebScraping/webgui.py
"""The web side in a window: search the open sources, review, download the legal copies, extract
(the averageScrap window). Reached from the one project GUI (mme_gui) or on its own with
`python -m WebScraping gui`. Each time it opens it first asks for the contact e-mail and points to the
API keys; the window waits for the answer. tkinter is imported lazily so importing this module stays cheap."""

import os


def _window(parent):
    """A new top-level window: the application's root when there is no parent (standalone), else a
    child of the window that opened it (inside the project hub)."""
    import tkinter as tk
    return tk.Tk() if parent is None else tk.Toplevel(parent)


def open_web(parent=None, job_path=None, output_dir=None, workers=4):
    """The Web scraping window, after the "Before you start" question (closing that closes the window).
    `job_path`, `output_dir`, `workers`: the options of `python -m WebScraping gui` (default: the job
    file configs/sse.yaml, made from the shipped one if missing, and WebScraping/web_output)."""
    from WebScraping.averageScrap.about import DEFAULT_OUTPUT, ensure_default_job
    from WebScraping.averageScrap.gui.app import App
    from WebScraping.averageScrap.job import load_env
    load_env()
    job = job_path or ensure_default_job()  # a fresh folder: start it off with the shipped job file
    win = _window(parent)
    app = App(win, job if os.path.exists(job) else "", output_dir or DEFAULT_OUTPUT, workers)
    win.app = app  # a hook for the tests
    ask_before_start(win, app)
    return win


def ask_before_start(win, app):
    """The question shown each time the window opens (the e-mail, the API keys). The window behind it
    waits until it is answered; cancelling it closes the window."""
    import tkinter as tk
    from WebScraping.averageScrap import job
    from WebScraping.averageScrap.gui.dialogs import StartDialog
    question = StartDialog(win, on_continue=lambda: None, on_cancel=app.close, path=job.ENV_PATH)

    def hold() -> None:  # a grab needs the dialog on screen: try again until it is
        try:
            if question.winfo_exists():
                question.grab_set()
        except tk.TclError:
            if question.winfo_exists():
                question.after(100, hold)
    question.after_idle(hold)
    return question


def main(argv=None, job_path=None, output_dir=None, workers=4) -> None:
    """`python -m WebScraping gui [--job FILE] [--output DIR] [--workers N] [--verbose]` (and `mme-web gui`):
    the Web scraping window on its own."""
    import logging
    from LocalExtraction.about import enter_project_home
    if argv is not None:
        from WebScraping.averageScrap.cli import parse_args
        args = parse_args(["gui", *argv])
        job_path, output_dir, workers = args.job, args.output, args.workers
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
    enter_project_home("web", "dois")
    root = open_web(None, job_path, output_dir, workers)
    root.mainloop()
