# gui/__init__.py
"""The window of AutoMatExtract: the second gate (the first is the terminal, main.py).

    python main.py gui          (or: python -m gui)

Two panels side by side — the articles on this computer, the articles from the web — that write one
database. Both run the code the terminal commands run (main.run_extraction, web.harvest.Harvest),
so the two gates cannot drift apart."""

from gui.app import main

__all__ = ["main"]
