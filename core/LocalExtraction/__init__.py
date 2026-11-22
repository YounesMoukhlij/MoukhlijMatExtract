# LocalExtraction/__init__.py
"""Project 1 — the local side of MoukhlijMatExtract.

Turns a folder of battery/materials-science PDFs (papers/ by default) into a structured database
(local_output/): parses text, tables, figures and equations (OCR for scanned pages), extracts the
materials and their properties, ranks the candidates and exports linked CSV, Excel and JSON.

    python -m LocalExtraction            (from the project root; the window: python -m LocalExtraction gui)

The web project (WebScraping/) runs the same pipeline on the PDFs it fetches.
"""


def _no_csv_cell_limit() -> None:
    """Python's CSV reader refuses a cell over 131,072 characters by default, and a record's abstract or a table's
    text can be longer (a Zenodo record: 465,682 characters): the reading stopped there, and the download with it.
    The limit is lifted for the whole program as soon as it is loaded (the largest number this system allows)."""
    import csv
    import sys
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:  # Windows: a C long is 32 bits
            limit //= 10


_no_csv_cell_limit()


def _console_never_fails() -> None:
    """A console that cannot show a character (Windows when the output goes to a file or a pipe: cp1252 has no ✓,
    ≥, −, →, ⚠) shows “?” for it, instead of the program stopping with UnicodeEncodeError — as `mme-eval --help >
    help.txt` did on Windows. A UTF-8 console (macOS, Linux, Windows Terminal) is left as it is."""
    import sys
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "").replace("_", "")
        if encoding and encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:  # a stream that cannot be changed: left as it is
                pass


_console_never_fails()
