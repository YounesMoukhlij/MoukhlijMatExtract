# LocalExtraction/tables.py
"""Tables printed without ruling lines, found from their caption.

pdfplumber's own table finder (parser._extract_tables) sees a table by the lines drawn around its cells.
Most journals print their tables without them: only the alignment of the text makes the columns. Such a
table is looked for under each "Table N" caption of a page: the lines below it, down to the first line of
running text (or the next caption), are its rows; the words of a row that stand close together make a cell,
and the cells are put in columns by where they stand across the rows. The first rows that hold no number
are the header (a header written on two lines, "σbulk" over "(S cm−1)", is one cell per column)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

_CAPTION = re.compile(r"^(?:Table|TABLE)\s+([0-9]+|[IVX]+)\b")
_FIGURE = re.compile(r"^(?:Fig\.?|Figure|FIGURE|Scheme)\s*[0-9]")
_NUMBER = re.compile(r"\d")
_LONG_WORD = re.compile(r"[A-Za-z]{3,}")
_WORD_SPACE = 3.5  # points: words closer than this are one cell ("1.38 × 10−3", "Li 4 SiO 4")

Word = Dict[str, Any]


def _lines(words: Sequence[Word]) -> List[List[Word]]:
    """The words grouped into printed lines: a word belongs to the line whose middle it overlaps (a
    subscript, a superscript, sits a little lower or higher on the same line)."""
    lines: List[List[Word]] = []
    for word in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        middle = (word["top"] + word["bottom"]) / 2
        for line in lines:
            top, bottom = min(w["top"] for w in line), max(w["bottom"] for w in line)
            if top - 0.5 <= middle <= bottom + 0.5:
                line.append(word)
                break
        else:
            lines.append([word])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    lines.sort(key=lambda line: min(w["top"] for w in line))
    return lines


def _cells(line: Sequence[Word], gap: float) -> List[Tuple[float, float, str]]:
    """(x0, x1, text) of each cell of a line: words closer than `gap` belong to one cell."""
    cells: List[List[Any]] = []
    for word in line:
        if cells and word["x0"] - cells[-1][1] < gap:
            cells[-1][1] = max(cells[-1][1], word["x1"])
            cells[-1][2] += " " + word["text"]
        else:
            cells.append([word["x0"], word["x1"], word["text"]])
    return [(c[0], c[1], c[2]) for c in cells]


def _text(line: Sequence[Word]) -> str:
    return " ".join(w["text"] for w in line)


def _is_prose(line: Sequence[Word], width: float, cells: int) -> bool:
    """A line of running text: one stretch of words over most of the width, with many words."""
    span = max(w["x1"] for w in line) - min(w["x0"] for w in line)
    return cells <= 2 and span > 0.55 * width and len(_LONG_WORD.findall(_text(line))) >= 6


def _columns(rows: List[List[Word]]) -> List[Tuple[float, float]]:
    """The columns, as x ranges: where the words of the data rows stand, the stretches no word of them
    crosses being the gaps between columns (a gap narrower than a word space is inside a cell)."""
    data = [row for row in rows if sum(1 for w in row if _NUMBER.search(w["text"])) >= 2] or rows
    spans = sorted((w["x0"], w["x1"]) for row in data for w in row)
    columns: List[List[float]] = []
    for x0, x1 in spans:
        if columns and x0 <= columns[-1][1] + _WORD_SPACE:
            columns[-1][1] = max(columns[-1][1], x1)
        else:
            columns.append([x0, x1])
    return [(c[0], c[1]) for c in columns]


def _grid(rows: List[List[Word]]) -> List[List[str]]:
    """The rows as lists of cell texts, one per column: each word goes to the column it overlaps most
    (a word of a header spanning several columns, to the one it covers most)."""
    columns = _columns(rows)
    grid = []
    for row in rows:
        cells = [""] * len(columns)
        for word in row:
            x0, x1 = word["x0"], word["x1"]
            index = max(range(len(columns)),
                        key=lambda i: (min(x1, columns[i][1]) - max(x0, columns[i][0]), -abs(columns[i][0] - x0)))
            cells[index] = f"{cells[index]} {word['text']}".strip()
        grid.append(cells)
    return grid


def _with_header(grid: List[List[str]]) -> Optional[List[List[str]]]:
    """The header row first (the leading rows without a number, merged column by column; a unit line
    "(S cm−1)" under its name counts as header too), then the data rows. None when no row holds a number."""
    first_data = next((i for i, row in enumerate(grid)
                       if sum(1 for cell in row if _NUMBER.search(cell) and not re.fullmatch(r"\(.*\)", cell)) >= 2), None)
    if first_data is None:
        return None
    header = [""] * len(grid[0])
    for row in grid[:first_data]:
        header = [f"{h} {c}".strip() for h, c in zip(header, row)]
    data = [row for row in grid[first_data:] if any(row)]
    return [header] + data


def _overlap(a: Sequence[float], b: Sequence[float]) -> float:
    """The share of the smaller of two boxes (x0, top, x1, bottom) that the other covers."""
    width, height = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return width * height / smaller if smaller > 0 else 0.0


def caption_tables(page: Any, skip: Sequence[Tuple[float, float, float, float]] = ()) -> List[Tuple[str, List[List[str]]]]:
    """(caption number, rows — header first) of every table printed without ruling lines on a pdfplumber
    `page`, found under its "Table N" caption. A caption whose table lies in one of the `skip` boxes (the
    ruled tables already read) is left out."""
    words = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False, use_text_flow=False)
    if not words:
        return []
    lines = _lines(words)
    width, middle = float(page.width), float(page.width) / 2
    # One column of text, or two: in two, hardly a stretch of running text crosses the middle of the page.
    stretches = [cell for line in lines for cell in _cells(line, 8.0) if len(cell[2]) > 30]
    crossing = sum(1 for x0, x1, _ in stretches if x0 < middle - 20 and x1 > middle + 20)
    two_columns = bool(stretches) and crossing < 0.25 * len(stretches)
    found = []
    for index, line in enumerate(lines):
        # The caption is the stretch of the line that starts with "Table N" (the other column's text may
        # share its height).
        stretch = next((cell for cell in _cells(line, 8.0) if _CAPTION.match(cell[2])), None)
        if not stretch:
            continue
        caption = _CAPTION.match(stretch[2])
        first = next(w for w in line if w["x0"] >= stretch[0] - 0.1)
        wide = not two_columns or (stretch[0] < middle - 10 and stretch[1] > middle + 10)
        left, right = (0.0, width) if wide else ((0.0, middle + 2) if stretch[0] < middle else (middle - 2, width))
        if any(box[1] <= first["bottom"] + 40 and box[3] >= first["bottom"] and box[0] < right and box[2] > left
               for box in skip):
            continue  # a ruled table under this caption: already read
        # The caption's own lines: one stretch of text right under it.
        position = index + 1
        while position < len(lines):
            words_in = [w for w in lines[position] if left <= w["x0"] < right]
            if not words_in or len(_cells(words_in, 4.0)) > 1 or \
                    min(w["top"] for w in words_in) - max(w["bottom"] for w in lines[position - 1]) > 4:
                break
            position += 1
        rows: List[List[Word]] = []
        for candidate in lines[position:]:
            in_column = [w for w in candidate if left <= w["x0"] < right]
            if not in_column:
                continue
            text = _text(in_column)
            if _CAPTION.match(text) or _FIGURE.match(text):
                break
            if _is_prose(in_column, right - left, len(_cells(in_column, 8.0))):
                break
            rows.append(in_column)
        if len(rows) < 2:
            continue
        # A ruled table already read where these rows stand (its caption further away than the test above
        # allows): not read twice.
        area = (min(w["x0"] for r in rows for w in r), min(w["top"] for r in rows for w in r),
                max(w["x1"] for r in rows for w in r), max(w["bottom"] for r in rows for w in r))
        if any(_overlap(area, box) > 0.3 for box in skip):
            continue
        table = _with_header(_grid(rows))
        if table and len(table[0]) >= 2 and len(table) >= 2:
            found.append((caption.group(1), table))
    return found
