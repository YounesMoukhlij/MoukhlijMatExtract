# LocalExtraction/crashlog.py
"""When the program fails where it should not: the whole story written to a file a person can send with a report.

    ~/MoukhlijMatExtract/logs/crash_<date>_<time>.log     (the temporary folder when the main folder is not made)

It holds the version, the command, the Python, Tk and system it ran on, and the traceback — never a key or the
contents of .env. Every command installs it (about.enter_project_home), and every window passes its own errors to
it (watch)."""

from __future__ import annotations

import logging
import os
import platform
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

_INSTALLED = {"where": ""}


def _folder() -> Path:
    from . import about
    home = Path(about.PROJECT_HOME)
    return home / "logs" if home.is_dir() else Path(tempfile.gettempdir()) / "MoukhlijMatExtract-logs"


def report(exc_type, exc, tb, where: str = "") -> Optional[Path]:
    """Writes one crash; returns the file (None when even that could not be written)."""
    from .about import version_text
    try:
        tk = ""
        if "tkinter" in sys.modules:
            tk = f"Tk {sys.modules['tkinter'].TkVersion}"
        lines = [f"{version_text(where or _INSTALLED['where'])} — crash report",
                 f"When: {datetime.now().isoformat(timespec='seconds')}",
                 f"Command: {' '.join([os.path.basename(sys.argv[0]), *sys.argv[1:]]) if sys.argv else ''}",
                 f"Python {platform.python_version()} ({platform.python_implementation()}) · {tk} · "
                 f"{platform.platform()}",
                 f"Thread: {threading.current_thread().name}", "",
                 "".join(traceback.format_exception(exc_type, exc, tb))]
        folder = _folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"crash_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    except Exception:  # a crash report must never cause a second crash
        return None


def _said(path: Optional[Path]) -> str:
    return (f"The details are in {path} — please send that file with your report." if path
            else "The details could not be written to a file.")


def install(where: str = "") -> None:
    """Every uncaught error of the program, and of its worker threads, written to a crash file (Ctrl-C is no crash).
    The usual ending (the traceback in the terminal) still happens. Installing twice keeps one hook."""
    _INSTALLED["where"] = where or _INSTALLED["where"]
    # Each hook on its own: another library (a test runner) may have put back one of them since.
    if getattr(sys.excepthook, "_mme_crashlog", False) is not True:
        previous = sys.excepthook

        def hook(exc_type, exc, tb):
            if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
                print(f"\n{_said(report(exc_type, exc, tb))}", file=sys.stderr)
            previous(exc_type, exc, tb)

        hook._mme_crashlog = True
        hook.__wrapped__ = previous
        sys.excepthook = hook
    if getattr(threading.excepthook, "_mme_crashlog", False) is not True:
        previous_thread = threading.excepthook

        def thread_hook(args):
            if args.exc_type is not None and not issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
                logging.error(_said(report(args.exc_type, args.exc_value, args.exc_traceback)))
            previous_thread(args)

        thread_hook._mme_crashlog = True
        threading.excepthook = thread_hook


def watch(root) -> None:
    """A window's own errors (a button whose action fails) written to a crash file, and said in a message box."""
    def failed(exc_type, exc, tb):
        path = report(exc_type, exc, tb)
        traceback.print_exception(exc_type, exc, tb)
        try:
            from tkinter import messagebox
            messagebox.showerror("MoukhlijMatExtract", f"Something went wrong: {exc_type.__name__}: {exc}\n\n"
                                                       f"{_said(path)}", parent=root)
        except Exception:
            pass
    root.report_callback_exception = failed
    _close_on_signals(root)


def _close_on_signals(root) -> None:
    """Ctrl-C in the terminal, closing the terminal (SIGHUP) or a request to stop (SIGTERM): the window closes
    cleanly. Tk's own handler (macOS) shut Tcl down from whatever thread the signal reached, calling Python from
    there: Python then stopped with a fatal error ("Python quit unexpectedly"). Python runs its signal handlers on the
    main thread, where closing the window is safe."""
    import signal

    def close(signum, frame) -> None:
        # Only the loop is ended here: Tk may be in the middle of its own work (a resize), and closing the window
        # under it crashed Tk. run() closes the window once the loop has returned.
        try:
            root.quit()
        except Exception:
            pass

    close._mme_closes = True
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None:
            try:
                signal.signal(number, close)
            except (ValueError, OSError):  # not the main thread, or a signal this system does not let go of
                pass


def run(root) -> None:
    """The window's loop, then the window closed — outside any of Tk's work — when the loop ended without it (a stop
    signal, see _close_on_signals). Every window of the program runs through it."""
    root.mainloop()
    try:
        if root.winfo_exists():
            root.destroy()
    except Exception:  # already closed
        pass
