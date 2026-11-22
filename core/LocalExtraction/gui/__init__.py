# LocalExtraction/gui/__init__.py
"""The window of Project 1, the second gate to it (the first is the terminal, LocalExtraction/cli.py).

    python -m LocalExtraction gui

It runs the code the terminal runs (LocalExtraction.cli.run_extraction), so the two gates cannot
drift apart. Its frame (window.py), its table of activation energies (results.py) and its widgets
are the ones the window of the web project is made of too."""


def main(*args, **kwargs) -> None:
    from .app import main as run  # Tk is loaded only when a window is asked for
    run(*args, **kwargs)


__all__ = ["main"]
