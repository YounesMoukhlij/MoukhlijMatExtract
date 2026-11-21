# Classification/flow_window.py
"""“Classification flow…”: a window that draws how “▶ Classify everything” works — the button, the databases, the two
kinds of family, each property alone, each type, each origin, the quality filters, one table per branch — with the
numbers of the last classification where there is one."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

from LocalExtraction.gui import design, layout, theme

from .branches import FOLDER, read_tree

WIDTH, HEIGHT = 980, 1060
PROPERTIES = (("Activation energy", "eV"), ("Ionic conductivity", "S/cm"), ("Diffusion coefficient", "cm²/s"),
              ("Electronic conductivity", "S/cm"))
TYPES = ("bulk", "grain boundary", "total")
ORIGINS = ("experimental (measured)", "simulation (computed)")
QUALITY = ("the paper's own results only", "values the extraction flagged left out", "Arrhenius activation energies only",
           "conductivity and diffusion at room temperature", "the checks of the Verify tab applied")
_COMPONENT = {"bulk": "bulk", "grain boundary": "grain_boundary", "total": "total"}


from LocalExtraction.gui.single import once


def _families(n: int) -> str:
    return f"{n} family" if n == 1 else f"{n} families"


def numbers(out_dir: Path) -> Dict[str, object]:
    """What the last classification by property found, for the diagram's labels (empty before the first)."""
    rows = read_tree(out_dir)
    if not rows:
        return {}
    by_axis = {axis: len({r["family"] for r in rows if r["axis"] == axis}) for axis in ("crystal_structure",
                                                                                           "structure_families")}
    return {"branches": len(rows), "values": sum(int(r["n_values"]) for r in rows), "crystal": by_axis["crystal_structure"],
            "chemical": by_axis["structure_families"],
            "property": {p: sum(int(r["n_values"]) for r in rows if r["property"] == p) for p, _ in PROPERTIES},
            "type": {t: sum(int(r["n_values"]) for r in rows if r["component"] == _COMPONENT[t]) for t in TYPES},
            "origin": {o: sum(int(r["n_values"]) for r in rows if o.startswith(r["origin"])) for o in ORIGINS}}


class FlowDiagram(tk.Canvas):
    def __init__(self, parent: tk.Misc, found: Dict[str, object]):
        self.c = theme.palette(parent)
        super().__init__(parent, width=WIDTH, height=HEIGHT, background=self.c["card"], highlightthickness=0)
        self.found = found
        self.texts: List[str] = []  # every word drawn (for the tests)
        self.draw()

    # ------------------------------------------------------------------ drawing helpers
    def box(self, x: float, y: float, w: float, h: float, title: str, lines: Tuple[str, ...] = (), fill: str = "",
            ink: str = "", step: str = "", bold_size: int = 13) -> Tuple[float, float, float, float]:
        fill = fill or self.c["stripe"]
        ink = ink or self.c["ink"]
        self.create_rectangle(x, y, x + w, y + h, fill=fill, outline=self.c["line"], width=1)
        top = y + 12
        if step:
            r = 13
            self.create_oval(x + 12, y + h / 2 - r, x + 12 + 2 * r, y + h / 2 + r, fill=self.c["garnet"], outline="")
            digit = {"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5", "⑥": "6"}.get(step, step)
            self.create_text(x + 12 + r, y + h / 2, text=digit, fill="white", font=("TkDefaultFont", 13, "bold"))
        left = x + (52 if step else 0)
        width = w - (52 if step else 0)
        anchor_x = left + width / 2
        total = 18 + 17 * len(lines)
        top = y + (h - total) / 2 + 9
        self.create_text(anchor_x, top, text=title, fill=ink, font=("TkDefaultFont", bold_size, "bold"))
        self.texts.append(title)
        for index, line in enumerate(lines):
            self.create_text(anchor_x, top + 20 + 17 * index, text=line, fill=self.c["muted"] if ink == self.c["ink"]
                             else ink, font=("TkDefaultFont", 11))
            self.texts.append(line)
        return x, y, x + w, y + h

    def arrow(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.create_line(x1, y1, x2, y2, fill=self.c["accent"], width=2, arrow="last", arrowshape=(10, 12, 5))

    def chips(self, y: float, words: Tuple[str, ...], counts: Dict[str, int], x0: float = 90, x1: float = WIDTH - 90,
              h: float = 54) -> List[Tuple[float, float]]:
        gap = 18
        w = (x1 - x0 - gap * (len(words) - 1)) / len(words)
        centres = []
        for index, word in enumerate(words):
            x = x0 + index * (w + gap)
            extra = (f"{counts[word]:,} values",) if counts and word in counts else ()
            self.box(x, y, w, h, word, extra, bold_size=12)
            centres.append((x + w / 2, y))
        return centres

    # ------------------------------------------------------------------ the flow
    def draw(self) -> None:
        f, c, mid = self.found, self.c, WIDTH / 2
        # The button.
        self.box(mid - 200, 20, 400, 56, "▶  CLASSIFY EVERYTHING", ("one button",), fill=c["accent"], ink="white",
                 bold_size=15)
        self.arrow(mid, 76, mid, 104)
        self.box(110, 106, WIDTH - 220, 62, "Every database is read",
                 ("web_output, web_output_<job>, local_output … — a material found in several is one material",))
        # ① The families.
        self.arrow(mid, 168, mid - 220, 200)
        self.arrow(mid, 168, mid + 220, 200)
        crystal = (_families(f["crystal"]) if f else "garnet · NASICON · LISICON · argyrodite · perovskite …",)
        chemical = (_families(f["chemical"]) if f else "oxide · sulfide · halide · hydride · oxyhalide …",)
        self.box(60, 202, 400, 74, "Crystal family", crystal if not f else
                 ("garnet · NASICON · LISICON · perovskite …",) + crystal, step="①")
        self.box(WIDTH - 460, 202, 400, 74, "Chemical family", chemical if not f else
                 ("oxide · sulfide · halide · hydride …",) + chemical, step="①")
        self.arrow(260, 276, mid, 312)
        self.arrow(WIDTH - 260, 276, mid, 312)
        note = self.create_text(mid, 298, text="the same steps for every family", fill=c["muted"],
                                font=("TkDefaultFont", 10, "italic"))
        x1, y1, x2, y2 = self.bbox(note)
        self.tag_lower(self.create_rectangle(x1 - 8, y1 - 2, x2 + 8, y2 + 2, fill=c["card"], outline=""), note)
        # ② The properties.
        self.box(mid - 210, 316, 420, 40, "②  Property — one branch each, never mixed", bold_size=12, fill=c["card"])
        counts = {f"{p}": n for p, n in (f.get("property", {}) if f else {}).items()}
        words = tuple(p for p, _ in PROPERTIES)
        for x, y in self.chips(372, words, counts, x0=40, x1=WIDTH - 40, h=66):
            self.arrow(mid, 356, x, y)
        units = dict(PROPERTIES)
        gap, w = 18, (WIDTH - 80 - 18 * 3) / 4
        for index, word in enumerate(words):
            self.create_text(40 + index * (w + gap) + w / 2, 448, text=units[word], fill=c["muted"],
                             font=("TkDefaultFont", 10))
        # ③ The type.
        self.arrow(mid, 462, mid, 488)
        self.box(mid - 210, 490, 420, 40, "③  Type — the transport component", bold_size=12, fill=c["card"])
        for x, y in self.chips(546, TYPES, f.get("type", {}) if f else {}, h=54):
            self.arrow(mid, 530, x, y)
        # ④ The origin.
        self.arrow(mid, 600, mid, 626)
        self.box(mid - 210, 628, 420, 40, "④  Origin", bold_size=12, fill=c["card"])
        for x, y in self.chips(684, ORIGINS, f.get("origin", {}) if f else {}, x0=200, x1=WIDTH - 200, h=54):
            self.arrow(mid, 668, x, y)
        # ⑤ The quality filters.
        self.arrow(mid, 738, mid, 764)
        self.box(110, 766, WIDTH - 220, 120, "Quality filters — the defaults of the ML datasets", QUALITY, step="⑤")
        # ⑥ One table per branch.
        self.arrow(mid, 886, mid, 912)
        result = ((f"{f['branches']:,} branches · {f['values']:,} values in the last classification",) if f else ())
        self.box(110, 914, WIDTH - 220, 122, "One table per branch", (
            f"Classification/{FOLDER}/<family>/<property>/<type>/<origin>/",
            "dataset.csv — one row per material (median, spread, values, papers)",
            "values.csv — every value with its sentence and page") + result,
                 fill=c["selected"], step="⑥")


@once("classification-flow", "The Classification flow")
def open_flow(parent: tk.Misc, out_dir: Optional[Path] = None) -> tk.Toplevel:
    """The window of the classification flow, over the window it is opened from."""
    window = tk.Toplevel(parent)
    window.title("MoukhlijMatExtract · Classification flow")
    layout.place(window, (1040, 900), (760, 560), parent=parent)
    theme.apply(window)
    design.header(window, "Classification flow", "what “▶ Classify everything” does, step by step", compact=True)
    found = numbers(out_dir) if out_dir is not None else {}
    from LocalExtraction.gui.widgets import Scrolled
    area = Scrolled(window)
    area.pack(fill="both", expand=True)
    holder = ttk.Frame(area.inner, padding=(20, 14, 20, 14))
    holder.pack(fill="both", expand=True)
    window.diagram = FlowDiagram(holder, found)
    window.diagram.pack(anchor="n")
    design.website_line(window)
    window.bind("<Escape>", lambda event: design.go_back(window))
    return window
