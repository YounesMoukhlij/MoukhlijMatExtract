# WebScraping/__init__.py
"""Project 2 of MoukhlijMatExtract — the web side (averageScrap/): search the open sources (OpenAlex,
arXiv, Crossref and twenty-two more), keep the papers worth reading, fetch their legal open-access copies,
extract them. The PDFs go into WebScraping/papers/, the database into WebScraping/web_output/.

    python -m WebScraping            from the terminal
    python -m WebScraping gui        in a window (or use the one project GUI: python -m mme_gui)
"""

# Every web request of the web side pauses with its step and, when the internet is gone, waits for it
# to come back instead of failing (LocalExtraction/runcontrol.py).
from LocalExtraction import runcontrol as _runcontrol  # noqa: E402

_runcontrol.install()
