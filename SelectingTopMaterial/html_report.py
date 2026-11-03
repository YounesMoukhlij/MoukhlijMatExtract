# SelectingTopMaterial/html_report.py
"""The ranking as a page one opens in a browser: the classes and how many materials each holds, a
chart of every material against the limits, and the table — each material opening onto the values
it stands on, with the paper, the page and the sentence of each.

One file, self-contained: the data is written into the page (report_template.html), which loads
nothing from the network."""

from __future__ import annotations

import json
from pathlib import Path

from .exporters import payload, rule_rows, write_file
from .models import Selection, component_word
from .palette import REJECTED, class_colours

TEMPLATE = Path(__file__).with_name("report_template.html")
_PLACEHOLDER = "__SELECTION_DATA__"
# A sentence read in a PDF can hold anything, "</script>" included: what could end the data block
# early is written as an escape, which the page reads back as the character it stands for.
_ESCAPES = (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
            ("\N{LINE SEPARATOR}", "\\u2028"), ("\N{PARAGRAPH SEPARATOR}", "\\u2029"))


def render(selection: Selection) -> str:
    """The page, as text."""
    data = payload(selection)
    data["about"] = [[what, str(answer)] for what, answer in rule_rows(selection)]
    accepted = len(selection.criteria.classes) - 1
    for described, light, dark in zip(data["criteria"]["classes"], class_colours(accepted) + [REJECTED],
                                      class_colours(accepted, dark=True) + [REJECTED]):
        described["colour"], described["colour_dark"] = light, dark
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for character, escape in _ESCAPES:
        text = text.replace(character, escape)
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(_PLACEHOLDER) != 1:  # none: nowhere to put the data; two: one of them is not the data block
        raise ValueError(f"{TEMPLATE.name} must hold the mark {_PLACEHOLDER} once, where the data goes")
    page = template.replace(_PLACEHOLDER, text)
    if selection.component:  # the page names the component it ranks
        page = page.replace("Top materials by activation energy",
                            f"Top materials by {component_word(selection.component)} activation energy")
    return page


def write_html(selection: Selection, out_dir: Path) -> Path:
    page = render(selection)
    return write_file(out_dir / "report.html", lambda path: path.write_text(page, encoding="utf-8"))
