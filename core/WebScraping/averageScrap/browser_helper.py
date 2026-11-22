# WebScraping/averageScrap/browser_helper.py
"""The papers left on the hand list, fetched with your own browser: the helper opens their pages a few at a time in
your usual browser, you save each PDF (one click, or none when the browser downloads PDFs by itself), and the PDFs
that arrive in your Downloads folder are moved into the by_hand folder and taken in — DOI read from the PDF, title
checked, source recorded (by_hand.take_in).

Why a person stays in the loop: the sites still on the list (MDPI, ACS, RSC, SSRN …) refuse programs. A program
that disguised itself as a person to get through would break their terms and the program's rule of legal sources
only; your own browser, used by you, is how these sites are meant to be read.

What the watcher touches: only PDFs that were not in the Downloads folder when it started watching it (a snapshot
of the names, not the files' dates: some browsers keep the server's date on a download), and only those
whose pages name a DOI of the hand list. Any other file there is left exactly where it is."""

import logging
import os
import shutil
from typing import Dict, Iterable, List, Sequence, Set

from WebScraping.averageScrap.by_hand import BUSY, dois_in
from WebScraping.averageScrap.ids import normalize_doi

# The papers worth opening: every reason but "site busy", which the next download tries again by itself.
SKIPPED_REASONS = frozenset({BUSY})


def default_downloads() -> str:
    """The usual Downloads folder of this computer (~/Downloads)."""
    return os.path.join(os.path.expanduser("~"), "Downloads")


def to_open(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """The papers of the hand list the helper can bring in, in the list's order (the ones a person can get at once
    first): those with a DOI (the PDF is matched by it) and a link, and not merely waiting on a busy site."""
    return [row for row in rows if normalize_doi(row.get("doi", "")) and row.get("link")
            and row.get("reason") not in SKIPPED_REASONS]


def next_batch(rows: Sequence[Dict[str, str]], opened: Set[str], size: int) -> List[Dict[str, str]]:
    """The next `size` papers not opened yet (by key)."""
    return [row for row in rows if row["key"] not in opened][:max(0, size)]


class DownloadsWatcher:
    """Moves the PDFs of the hand list that arrive in `downloads` into `by_hand`. A file is moved once its size has
    stayed the same between two looks (a download still under way grows), and only when its pages or its name give
    a DOI of `wanted`. A PDF that was there when watching began, or of another paper, is never touched."""

    def __init__(self, downloads: str, by_hand: str, wanted: Iterable[str]):
        self.by_hand = by_hand
        self.wanted: Set[str] = {normalize_doi(d) for d in wanted if normalize_doi(d)}
        self.watch(downloads)

    def watch(self, downloads: str) -> None:
        """Watches `downloads` from now: the PDFs already there are left alone."""
        self.downloads = downloads
        self._sizes: Dict[str, int] = {}   # name -> size at the last look
        try:  # names already moved, found to be of no paper of the list, or there before
            self._settled: Set[str] = {n for n in os.listdir(downloads) if n.lower().endswith(".pdf")}
        except OSError:
            self._settled = set()

    def scan(self) -> List[str]:
        """One look at the Downloads folder. Returns the paths of the PDFs moved into the by_hand folder."""
        moved: List[str] = []
        try:
            names = os.listdir(self.downloads)
        except OSError as error:
            logging.warning(f"Browser helper: {self.downloads} cannot be read ({error}).")
            return moved
        for name in sorted(names):
            if name in self._settled or not name.lower().endswith(".pdf"):
                continue
            path = os.path.join(self.downloads, name)
            try:
                info = os.stat(path)
            except OSError:
                continue
            if not os.path.isfile(path):
                self._settled.add(name)
                continue
            size, before = info.st_size, self._sizes.get(name)
            self._sizes[name] = size
            if size == 0 or before != size:
                continue  # still being written: looked at again next time
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if not data.startswith(b"%PDF"):
                self._settled.add(name)
                continue
            if not any(doi in self.wanted for doi in dois_in(data, name)):
                self._settled.add(name)
                logging.info(f"Browser helper: {name} names no paper of the list — left in {self.downloads}.")
                continue
            target = self._free(name)
            try:
                os.makedirs(self.by_hand, exist_ok=True)
                shutil.move(path, target)
            except OSError as error:
                logging.warning(f"Browser helper: {name} could not be moved ({error}) — left in {self.downloads}.")
                continue
            self._settled.add(name)
            moved.append(target)
            logging.info(f"Browser helper: {name} moved into {self.by_hand}.")
        return moved

    def _free(self, name: str) -> str:
        """A path in the by_hand folder that holds no file yet: name.pdf, name (2).pdf …"""
        stem, ext = os.path.splitext(name)
        target, n = os.path.join(self.by_hand, name), 2
        while os.path.exists(target):
            target = os.path.join(self.by_hand, f"{stem} ({n}){ext}")
            n += 1
        return target
