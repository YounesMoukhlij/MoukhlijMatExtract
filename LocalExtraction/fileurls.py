# LocalExtraction/fileurls.py
"""Links to the files of this computer (source_url “file:…”), right on every system.

    file_url("/Users/me/papers/a b.pdf")      → "file:///Users/me/papers/a%20b.pdf"
    file_url(r"C:\\Users\\me\\a.pdf")           → "file:///C:/Users/me/a.pdf"         (on Windows)
    path_from_url("file:///C:/Users/me/a.pdf") → r"C:\\Users\\me\\a.pdf"            (on Windows)

Older databases hold links made as "file://" + the path: “file:///Users/me/a b.pdf” (a space not encoded) and, made
on Windows, “file://C:\\Users\\me\\a.pdf” (the drive read as a server name by any URL reader). `path_from_url` reads
those too, so nothing saved before has to be made again."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

_OLD_WINDOWS = re.compile(r"^file://([A-Za-z]:[\\/].*)$", re.IGNORECASE)


def file_url(path) -> str:
    """The link to a file of this computer (an absolute path, encoded as a URL is)."""
    return Path(os.path.abspath(str(path))).as_uri()


def path_from_url(url: str, windows: bool = os.name == "nt") -> str:
    """The path a “file:” link points to; "" for any other link."""
    url = (url or "").strip()
    if not url.lower().startswith("file:"):
        return ""
    old = _OLD_WINDOWS.match(url)
    if old:  # file://C:\dir\a.pdf — made by an older version on Windows
        return unquote(old.group(1)).replace("/", "\\") if windows else unquote(old.group(1))
    parts = urlsplit(url)
    path = unquote(parts.path)
    if windows:
        if re.match(r"^/[A-Za-z]:", path):  # /C:/Users/… → C:\Users\…
            path = path[1:]
        path = path.replace("/", "\\")
        if parts.netloc and parts.netloc.lower() != "localhost":  # file://server/share/a.pdf → \\server\share\a.pdf
            path = "\\\\" + parts.netloc + path
    return path
