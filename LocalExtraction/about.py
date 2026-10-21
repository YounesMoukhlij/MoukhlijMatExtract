# LocalExtraction/about.py
"""The name and author of the program, and where Project 1 reads and writes unless told otherwise."""

import os
import textwrap

NAME = "MoukhlijMatExtract"
ABBREVIATION = "MME"
FULL_NAME = f"{NAME} ({ABBREVIATION})"
AUTHOR = "Younes Moukhlij"
CREDIT_TEXT = (f"{FULL_NAME} — Created by {AUTHOR} "
               "(Software Engineering student at 1337 Coding School, "
               "PhD researcher at FPK, USMS)")
DESCRIPTION = (
    "Turns a folder of battery/materials-science PDFs into a structured, queryable database: "
    "parses text, tables, figures and equations (with OCR fallback for scanned pages), extracts "
    "materials and their properties, and exports linked CSV, Excel and JSON."
)

# Relative to the project root, where the commands are run from.
DEFAULT_INPUT = os.path.join("LocalExtraction", "papers")
DEFAULT_OUTPUT = os.path.join("LocalExtraction", "local_output")


def print_banner(title: str, description: str) -> None:
    """Prints a small decorated header to the console: the title, a one-line description and the
    author credit (see CREDIT_TEXT for the plain-text version used in --help, where box-drawing
    characters would look out of place)."""
    body_lines = (
        textwrap.wrap(description, width=58)
        + [""]
        + [
            AUTHOR,
            "Software Engineering student · 1337 Coding School",
            "PhD Researcher · FPK, USMS",
        ]
    )
    width = max(len(title), *(len(l) for l in body_lines)) + 4

    print("╭" + "─" * width + "╮")
    print("│ " + title.center(width - 2) + " │")
    print("├" + "─" * width + "┤")
    for l in body_lines:
        print("│ " + l.center(width - 2) + " │")
    print("╰" + "─" * width + "╯")
