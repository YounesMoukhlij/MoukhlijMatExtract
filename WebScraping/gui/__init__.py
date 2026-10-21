# WebScraping/gui/__init__.py
"""The window of Project 2, the second gate to it (the first is the terminal, WebScraping/cli.py).

    python -m WebScraping gui

The steps of `python -m WebScraping` as buttons — search, (review in the table,) download,
extract — run by the same WebScraping.harvest.Harvest, on the same ledger and review list, so a run
started in the terminal goes on here and the other way round."""


def main(*args, **kwargs) -> None:
    from .app import main as run  # Tk is loaded only when a window is asked for
    run(*args, **kwargs)


__all__ = ["main"]
