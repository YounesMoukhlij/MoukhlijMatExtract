# mme_gui/process_flow.py
"""“Process flow”: the whole of MoukhlijMatExtract from scratch, as the windows show it — set up once, build the
database (your own PDFs, or the literature from the web: Fetch DOIs → Search → review → Download → Extract), use it
(check values by hand, rank, classify, ML datasets), measure the accuracy, share it. Each step names the window and
the button; the step of the window it was opened from is marked “You are here”.

Every window with a header band has the floating “⇄ Flow” button (design.header calls `add_flow_button`): a click
opens this window, a drag moves the button out of the way. A click on a step says what it is, why it matters and
where to click; the steps of the five parts can be opened from there."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from LocalExtraction.gui.single import once

from .make_guide import COLUMN_X, BOX_W, WIDTH, _rounded, ink_on

# (key, title, purpose, colour light, colour dark) — the stages of the Make commands window, in the same colours.
STAGES = (
    ("start", "1 · Start", "Once: install, read the requirements, create the main folder.", "#2a78d6", "#3987e5"),
    ("build", "2 · Build the database", "Papers into tables: your own PDFs, or legal copies found on the web.",
     "#eb6834", "#d95926"),
    ("use", "3 · Use the database", "Check values by hand, rank the materials, classify them, datasets for ML.",
     "#1baf7a", "#199e70"),
    ("measure", "4 · Measure the accuracy", "How right is the extraction? Annotate a sample, score, compare.",
     "#6250d6", "#9085e9"),
    ("share", "5 · Share and publish", "The dataset on Zenodo; every table and figure of the article.",
     "#e34948", "#e66767"),
)
STAGE = {key: (title, about, light, dark) for key, title, about, light, dark in STAGES}


@dataclass(frozen=True)
class Step:
    key: str
    stage: str
    title: str
    where: str          # the window › the button (or the terminal)
    what: str
    why: str
    opens: str = ""     # a part the window can open: local, web, rank, classify, ml


STEPS: Tuple[Step, ...] = (
    Step("install", "start", "Install the program", "Terminal, once: make install",
         "Creates the program's environment and installs everything it needs (and the language model).",
         "Done once per computer; make install-locked installs the exact versions used for published results."),
    Step("requirements", "start", "Read the Requirements", "Main window › ⚠ Requirements",
         "What the program needs (Tesseract for scanned PDFs, the language model) and how to use it.",
         "Two minutes that save an hour: the button turns green once read."),
    Step("folder", "start", "Create the main folder", "Main window › Create the main results folder",
         "Makes ~/MoukhlijMatExtract with its job files (configs/) and the documents.",
         "Every part reads and writes there, so they find each other's results."),
    Step("hub", "start", "The main window", "The Dock icon, or mme-gui",
         "One button per part, with the status of each and its results.",
         "Where every step starts; “‹ Back” in each window comes back here."),
    Step("local", "build", "① Local extraction", "Main window › 1 · Local extraction",
         "Reads the PDFs you put in LocalExtraction/papers and extracts their materials and values.",
         "When you already have the papers: put them in the folder and press Start. Only new PDFs are read again.",
         "local"),
    Step("job", "build", "Choose a job", "Web scraping › Job file · Search settings… · API keys…",
         "The job: the keywords, the years, the sources to search; your API keys for the publishers.",
         "One job per topic (garnet, NASICON …), each with its own papers and its own database.", "web"),
    Step("dois", "build", "1 · Fetch DOIs", "Web scraping › 1 · Fetch DOIs",
         "Asks OpenAlex, Crossref, Semantic Scholar and arXiv for the DOIs of the job's keywords.",
         "Builds the list of papers to retrieve before anything is downloaded.", "web"),
    Step("search", "build", "2 · Search", "Web scraping › 2 · Search",
         "Searches with the saved keywords and DOIs, completes each paper's record and abstract, scores it.",
         "Finds the papers on the topic and proposes those worth downloading.", "web"),
    Step("review", "build", "Review the candidates", "Web scraping › Candidates tab › ✓ Yes / ✗ No",
         "The papers proposed, best first: keep or drop them.",
         "You decide what is downloaded; the program learns from your choices.", "web"),
    Step("download", "build", "3 · Download", "Web scraping › 3 · Download (then “Get the rest with my browser…”)",
         "Downloads the legal copies: open access, and the publishers' services with your keys.",
         "Legal sources only; what has no free copy goes to a list for you to get by hand.", "web"),
    Step("extract", "build", "4 · Extract", "Web scraping › 4 · Extract",
         "Extracts the downloaded PDFs into the job's database (web_output_<job>).",
         "The same extraction as for your own PDFs, page and sentence recorded for each value.", "web"),
    Step("verify", "use", "Check values by hand", "Local or Web window › Verify tab",
         "Marks extracted activation energies correct, corrected or wrong.",
         "Optional, and worth it: the ranking and the ML datasets apply your checks.", "local"),
    Step("rank", "use", "③ Ranking", "Main window › 3 · Ranking › Rank",
         "Ranks the materials by activation energy, one ranking per transport component.",
         "The best candidates in the database, with the evidence behind each rank.", "rank"),
    Step("classify", "use", "④ Classification", "Main window › 4 · Classification › ▶ Classify everything",
         "Sorts the materials by crystal family and chemical family, then by property, type and origin.",
         "Compare like with like; it makes the families the ML datasets are built from.", "classify"),
    Step("ml", "use", "⑤ ML datasets", "Main window › 5 · ML datasets",
         "Family → property → type → origin → filters → Generate: a clean dataset in “Ready for ML”.",
         "Comparable values, each measurement counted once, with a datasheet.", "ml"),
    Step("evaluate", "measure", "Evaluate…", "Local or Web window › Evaluate… › Make the Excel file",
         "Draws papers at random and writes the workbook to annotate.",
         "A journal will ask how often the extraction is right: this is where it starts.", "web"),
    Step("score", "measure", "Compute the scores", "Evaluate… › Compute the scores",
         "Precision, recall and F1 with 95 % intervals, from the papers you annotated.",
         "The accuracy figure of the article — measured again after each change of the program.", "web"),
    Step("benchmark", "measure", "Benchmark · gold standard", "Terminal: mme-eval benchmark · mme-eval gold",
         "MME against a keyword baseline and other tools; the annotated papers as a public dataset.",
         "Shows it beats simpler methods, and gives others a reference set to cite."),
    Step("release", "share", "Release the dataset", "Terminal: make release",
         "The databases, ranking and classification, licence-checked, with a datasheet and checksums.",
         "Upload the .zip to Zenodo and cite the dataset by its DOI."),
    Step("paper", "share", "Every table and figure", "Terminal: make paper",
         "Makes the article's tables and figures again from the data, the environment recorded.",
         "Reproducibility: a reviewer runs one command and gets your numbers."),
)
BY_KEY: Dict[str, Step] = {s.key: s for s in STEPS}

BOX_H = 76
NODES: Dict[str, Tuple[int, int]] = {
    "install": (0, 70), "requirements": (1, 70), "folder": (2, 70), "hub": (3, 70),
    "local": (0, 290), "job": (1, 290), "dois": (2, 290), "search": (3, 290),
    "review": (1, 410), "download": (2, 410), "extract": (3, 410),
    "verify": (0, 660), "rank": (1, 660), "classify": (2, 660), "ml": (3, 660),
    "evaluate": (0, 826), "score": (2, 826), "benchmark": (3, 826),
    "release": (0, 990), "paper": (2, 990),
}
PLACES: Dict[str, Tuple[int, int, int, str, str]] = {
    "database": (0, 3, 535, "Your database",
                 "LocalExtraction/local_output · WebScraping/web_output_<job> — see it with “Results…”"),
    "annotate": (1, 1, 826, "You annotate", "correct / partly / wrong, and the values missed"),
    "zenodo": (1, 1, 990, "Zenodo deposit", "the dataset, citable by DOI"),
    "article": (3, 3, 990, "The article", "every number reproducible"),
}
EDGES: Tuple[Tuple[str, str], ...] = (
    ("install", "requirements"), ("requirements", "folder"), ("folder", "hub"),
    ("hub", "local"), ("hub", "job"), ("job", "dois"), ("dois", "search"), ("search", "review"),
    ("review", "download"), ("download", "extract"),
    ("local", "database"), ("extract", "database"),
    ("database", "verify"), ("database", "rank"), ("database", "classify"), ("classify", "ml"),
    ("evaluate", "annotate"), ("annotate", "score"), ("score", "benchmark"),
    ("release", "zenodo"), ("paper", "article"),
)
LANES = (("start", 22, 170), ("build", 188, 605), ("use", 623, 760), ("measure", 778, 922), ("share", 940, 1086))
HEIGHT = 1100

# The window a flow is opened from (its header's title) → the steps it does: “You are here”.
HERE: Dict[str, Tuple[str, ...]] = {
    "MoukhlijMatExtract (MME)": ("hub",),
    "Local extraction": ("local", "verify", "evaluate"),
    "Web scraping": ("job", "dois", "search", "review", "download", "extract"),
    "Ranking the materials": ("rank",),
    "Classification": ("classify",),
    "Classification flow": ("classify",),
    "ML datasets": ("ml",),
}


def here_of(title: str) -> Tuple[str, ...]:
    return HERE.get(title, ())


class FlowDiagram:
    """The process on a canvas; a click on a step calls `on_pick(key)`."""

    def __init__(self, canvas, colours: Dict[str, str], dark: bool, on_pick, here: Tuple[str, ...] = ()):
        self.canvas, self.c, self.dark, self.on_pick, self.here = canvas, colours, dark, on_pick, here
        self.items: Dict[str, int] = {}
        self.anchors: Dict[str, Tuple[float, float, float, float]] = {}
        self.texts: List[str] = []
        self.chosen: Optional[str] = None
        self.draw()

    def colour(self, stage: str) -> str:
        return STAGE[stage][3 if self.dark else 2]

    def text(self, x, y, words, **options):
        self.texts.append(words)
        return self.canvas.create_text(x, y, text=words, **options)

    def label(self, x, y, words, ink, font):
        item = self.text(x, y, words, anchor="w", fill=ink, font=font)
        x1, y1, x2, y2 = self.canvas.bbox(item)
        back = self.canvas.create_rectangle(x1 - 4, y1 - 1, x2 + 4, y2 + 1, fill=self.c["stripe"], outline="")
        self.canvas.tag_raise(item, back)
        return item

    def box(self, key: str, column: int, y: float) -> None:
        cv, c, step = self.canvas, self.c, BY_KEY[key]
        x, tag = COLUMN_X[column], f"s:{key}"
        here = key in self.here
        _rounded(cv, x + 2, y + 3, x + BOX_W + 2, y + BOX_H + 3, 12, fill="#0b0b0b" if self.dark else "#dfe3ea",
                 outline="")
        outline = _rounded(cv, x, y, x + BOX_W, y + BOX_H, 12, fill=c["selected"] if here else c["card"],
                           outline=c["accent"] if here else c["line"], width=2 if here else 1, tags=tag)
        cv.create_rectangle(x + 1, y + 10, x + 6, y + BOX_H - 10, fill=self.colour(step.stage), outline="", tags=tag)
        self.text(x + 16, y + 18, step.title, anchor="w", fill=c["ink"], font=("TkDefaultFont", 12, "bold"), tags=tag)
        self.text(x + 16, y + 46, step.where, anchor="w", fill=c["muted"], font=("TkDefaultFont", 10),
                  width=BOX_W - 24, tags=tag)
        if here:
            pill_x = x + BOX_W - 88
            _rounded(cv, pill_x, y - 10, pill_x + 84, y + 10, 10, fill=c["garnet"], outline="", tags=tag)
            self.text(pill_x + 42, y, "You are here", fill="white", font=("TkDefaultFont", 9, "bold"), tags=tag)
        self.items[key] = outline
        self.anchors[key] = (x, y, x + BOX_W, y + BOX_H)
        cv.tag_bind(tag, "<Button-1>", lambda event: self.choose(key, tell=True))
        cv.tag_bind(tag, "<Enter>", lambda event: cv.configure(cursor="hand2"))
        cv.tag_bind(tag, "<Leave>", lambda event: cv.configure(cursor=""))

    def place(self, key: str, first: int, last: int, y: float, title: str, line: str) -> None:
        cv, c = self.canvas, self.c
        x0, x1 = COLUMN_X[first], COLUMN_X[last] + BOX_W
        height = BOX_H - 14
        _rounded(cv, x0, y, x1, y + height, 12, fill=c["selected"], outline=c["accent"], width=1, dash=(4, 3))
        self.text(x0 + 16, y + 18, title, anchor="w", fill=c["ink"], font=("TkDefaultFont", 12, "bold"))
        self.text(x0 + 16, y + 40, line, anchor="w", fill=c["muted"], font=("TkDefaultFont", 10), width=x1 - x0 - 26)
        self.anchors[key] = (x0, y, x1, y + height)

    def edge(self, a: str, b: str) -> None:
        ax0, ay0, ax1, ay1 = self.anchors[a]
        bx0, by0, bx1, by1 = self.anchors[b]
        line = {"fill": self.c["accent"], "width": 2, "arrow": "last", "arrowshape": (9, 11, 4)}
        cv = self.canvas
        if abs(ay0 - by0) < 5:
            cv.create_line(ax1, (ay0 + ay1) / 2, bx0, (by0 + by1) / 2, **line)
            return
        if ax1 - ax0 > bx1 - bx0 + 10:
            x = (bx0 + bx1) / 2
            cv.create_line(x, ay1, x, by0, **line)
            return
        start = (ax0 + ax1) / 2
        if bx1 - bx0 > ax1 - ax0 + 10:
            cv.create_line(start, ay1, start, by0, **line)
            return
        end = (bx0 + bx1) / 2
        turn = next((bottom + 8 for _, top, bottom in LANES if ay1 < bottom < by0), by0 - 14)
        cv.create_line(start, ay1, start, turn, end, turn, end, by0, **line)

    def draw(self) -> None:
        for stage, top, bottom in LANES:
            _rounded(self.canvas, 12, top, WIDTH - 12, bottom, 18, fill=self.c["stripe"], outline="")
        for key, (first, last, y, title, line) in PLACES.items():
            self.place(key, first, last, y, title, line)
        for key, (column, y) in NODES.items():
            self.box(key, column, y)
        for a, b in EDGES:
            self.edge(a, b)
        for stage, top, _ in LANES:
            title, about, *_ = STAGE[stage]
            dot = self.canvas.create_oval(26, top + 14, 38, top + 26, fill=self.colour(stage), outline="")
            name = self.label(46, top + 20, title, self.c["ink"], ("TkDefaultFont", 13, "bold"))
            self.label(self.canvas.bbox(name)[2] + 18, top + 20, about, self.c["muted"], ("TkDefaultFont", 10))
            self.canvas.tag_raise(dot)
        quiet, italic = self.c["muted"], ("TkDefaultFont", 10, "italic")
        self.label(COLUMN_X[0], 262, "Your own PDFs", quiet, italic)
        self.label(COLUMN_X[1], 262, "or papers from the web (legal copies only)", quiet, italic)
        for key in self.items:
            self.canvas.tag_raise(f"s:{key}")

    def choose(self, key: str, tell: bool = False) -> None:
        if self.chosen in self.items:
            old = self.chosen
            here = old in self.here
            self.canvas.itemconfigure(self.items[old], width=2 if here else 1,
                                      outline=self.c["accent"] if here else self.c["line"])
        self.chosen = key
        self.canvas.itemconfigure(self.items[key], width=3, outline=self.c["accent"])
        if tell:
            self.on_pick(key)


INTRO = ("The whole process, from scratch, top to bottom. Each step says the window and the button.\n\n"
         "Click a step: what it does, why it matters — and the parts open from here.\n\n"
         "“You are here” marks the step of the window you came from.")


def _here_again(window, parent, here_title: str = "") -> None:
    """The flow already open, asked from another window: “You are here” moves to that window's steps."""
    window.set_here(here_title)


@once("process-flow", "The Process flow", again=_here_again)
def open_flow(parent, here_title: str = "") -> "object":
    """The window. `here_title`: the header title of the window it is opened from (its steps are marked). One is open
    at a time: asked again, it comes back with the steps of the window it is asked from marked."""
    import tkinter as tk
    from tkinter import ttk

    from LocalExtraction.gui import design, layout, theme
    from LocalExtraction.gui.widgets import WrapLabel

    win = tk.Toplevel(parent)
    win.title("MoukhlijMatExtract · Process flow")
    layout.place(win, (1300, 880), (900, 560), parent=parent)
    theme.apply(win)
    colours, dark = theme.palette(win), theme.is_dark(win)
    design.header(win, "Process flow", "the whole of MoukhlijMatExtract, from scratch, window by window",
                  compact=True, flow=False)
    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=14, pady=(10, 0))
    left = ttk.Frame(body)
    left.pack(side="left", fill="both", expand=True)
    canvas = tk.Canvas(left, width=WIDTH, background=colours["card"], highlightthickness=0,
                       scrollregion=(0, 0, WIDTH, HEIGHT))
    bar = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    panel = ttk.Frame(body, padding=(18, 4, 6, 14), width=340)
    panel.pack(side="right", fill="y")
    panel.pack_propagate(False)
    badge = tk.Label(panel, text="How to read it", font=("TkDefaultFont", 10, "bold"), padx=8, pady=2,
                     background=colours["accent"], foreground=ink_on(colours["accent"]))
    badge.pack(anchor="w")
    title = ttk.Label(panel, text="", font=("TkDefaultFont", 15, "bold"))
    title.pack(anchor="w", pady=(10, 4))
    intro = WrapLabel(panel, text=INTRO, wraplength=310)
    intro.pack(anchor="w", fill="x")
    sections = {key: (ttk.Label(panel, text=head, style="Section.TLabel"), WrapLabel(panel, text="", wraplength=310))
                for key, head in (("where", "Where"), ("what", "What it does"), ("why", "Why it matters"))}
    open_button = ttk.Button(panel, text="", style="Next.TButton")

    here = here_of(here_title)
    state = {"diagram": None, "here": here}

    def show(key: str) -> None:
        here, diagram = state["here"], state["diagram"]
        step = BY_KEY[key]
        stage_title, _, light, darker = STAGE[step.stage]
        colour = darker if dark else light
        badge.configure(text=stage_title, background=colour, foreground=ink_on(colour))
        title.configure(text=step.title + ("   · you are here" if key in here else ""))
        intro.pack_forget()
        for head, words in sections.values():
            head.pack_forget()
            words.pack_forget()
        open_button.pack_forget()
        for name, (head, words) in sections.items():
            words.configure(text=getattr(step, name))
            head.pack(anchor="w", pady=(10, 2))
            words.pack(anchor="w", fill="x")
        if step.opens:
            label = {"local": "Open Local extraction", "web": "Open Web scraping", "rank": "Open Ranking",
                     "classify": "Open Classification", "ml": "Open ML datasets"}[step.opens]
            open_button.configure(text=label, command=lambda: open_part(step.opens))
            open_button.pack(anchor="w", pady=(16, 0))
        diagram.choose(key)
        win.chosen = key

    def open_part(part: str) -> None:
        from . import hub
        opener = {"local": hub.open_local, "web": hub.open_web, "rank": hub.open_rank,
                  "classify": hub.open_classify, "ml": hub.open_ml}[part]
        hub._open(win._root(), opener, what=dict(local="Local extraction", web="Web scraping", rank="Ranking",
                                                 classify="Classification", ml="ML datasets")[part])

    def set_here(title_: str) -> None:
        """The steps of the window `title_` marked “You are here” (the diagram drawn again), and brought into view."""
        state["here"] = here_of(title_)
        canvas.delete("all")
        state["diagram"] = FlowDiagram(canvas, colours, dark, show, state["here"])
        win.diagram, win.here, win.chosen = state["diagram"], state["here"], None
        if state["here"]:  # the window it came from in view
            canvas.yview_moveto(max(0.0, (NODES[state["here"][0]][1] - 120) / HEIGHT))

    def wheel(event) -> None:
        step = -1 if (event.num == 4 or getattr(event, "delta", 0) > 0) else 1
        canvas.yview_scroll(step * max(1, abs(getattr(event, "delta", 0)) // 120 or 1), "units")
    canvas.bind("<Enter>", lambda event: [canvas.bind_all(s, wheel) for s in ("<MouseWheel>", "<Button-4>", "<Button-5>")])
    canvas.bind("<Leave>", lambda event: [canvas.unbind_all(s) for s in ("<MouseWheel>", "<Button-4>", "<Button-5>")])

    footer = ttk.Frame(win, padding=(14, 8))
    footer.pack(fill="x")
    ttk.Label(footer, style="Muted.TLabel", text="The “⇄ Flow” button of every window opens this.").pack(side="left")
    design.back_button(footer, win).pack(side="right")
    design.website_line(win)
    win.bind("<Escape>", lambda event: design.go_back(win))
    win.show, win.set_here = show, set_here
    set_here(here_title)
    return win


# ---------------------------------------------------------------------------------------------- the floating button
# Where the button may sit, in order: (anchor, relx, rely, x, y). The first that covers no control is taken.
SPOTS = (("se", 1.0, 1.0, -18, -40), ("se", 1.0, 1.0, -46, -40), ("se", 1.0, 1.0, -46, -76), ("s", 0.5, 1.0, 0, -40),
         ("sw", 0.0, 1.0, 18, -40), ("se", 1.0, 1.0, -46, -120), ("e", 1.0, 0.5, -46, 0), ("sw", 0.0, 1.0, 18, -76))


def _controls(window, skip):
    """The rectangles (in the window's coordinates) of what a person clicks or types in: buttons, fields, boxes,
    scroll bars, links."""
    import tkinter as tk
    from tkinter import ttk
    kinds = (ttk.Button, tk.Button, ttk.Entry, tk.Entry, ttk.Combobox, ttk.Checkbutton, tk.Checkbutton,
             ttk.Radiobutton, ttk.Scrollbar, tk.Scrollbar, ttk.Spinbox, ttk.Scale)
    x0, y0 = window.winfo_rootx(), window.winfo_rooty()
    found = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Toplevel) or child is skip:
                continue
            try:
                if not child.winfo_ismapped():
                    continue
                link = isinstance(child, tk.Label) and str(child.cget("cursor")) == "hand2"
                if isinstance(child, kinds) or link:
                    found.append((child.winfo_rootx() - x0, child.winfo_rooty() - y0,
                                  child.winfo_width(), child.winfo_height()))
            except tk.TclError:
                continue
            walk(child)
    walk(window)
    return found


def _rectangle(spot, width, height, button_w, button_h):
    anchor, relx, rely, dx, dy = spot
    x, y = relx * width + dx, rely * height + dy
    left = x - button_w if "e" in anchor else x if "w" in anchor else x - button_w / 2
    top = y - button_h if anchor.startswith("s") else y - button_h / 2 if anchor in ("e", "w") else y
    return left, top, button_w, button_h


def free_spot(window, button):
    """The first of SPOTS where the button covers no control of the window (the first when none is free)."""
    width, height = window.winfo_width(), window.winfo_height()
    bw, bh = button.winfo_reqwidth(), button.winfo_reqheight()
    controls = _controls(window, button)
    for spot in SPOTS:
        x, y, w, h = _rectangle(spot, width, height, bw, bh)
        if x < 0 or y < 0 or x + w > width or y + h > height:
            continue
        if not any(x < cx + cw and cx < x + w and y < cy + ch and cy < y + h for cx, cy, cw, ch in controls):
            return spot
    return SPOTS[0]


def add_flow_button(window, title: str):
    """The floating “⇄ Flow” button of a window, above its content: a click opens the process flow (the window's
    steps marked), a drag moves it. It sits where it covers no button, field or scroll bar (SPOTS), looked for again
    when the window is resized — until it is dragged: then it stays where it was put. Returns it."""
    import tkinter as tk

    from LocalExtraction.gui import theme
    colours = theme.palette(window)
    rest, lit = colours["accent"], colours["garnet"]
    button = tk.Label(window, text="⇄  Flow", cursor="hand2", font=("TkDefaultFont", 11, "bold"),
                      background=rest, foreground=ink_on(rest), padx=12, pady=5, relief="flat", bd=0)
    state = {"spot": SPOTS[0], "dragged": False, "pending": None, "size": None}

    def put() -> None:
        anchor, relx, rely, x, y = state["spot"]
        try:
            button.place(relx=relx, rely=rely, x=x, y=y, anchor=anchor)
            button.lift()
        except tk.TclError:
            pass

    def settle() -> None:
        state["pending"] = None
        try:
            if not window.winfo_exists() or state["dragged"]:
                return
            state["spot"] = free_spot(window, button)
        except tk.TclError:
            return
        put()

    def resized(event) -> None:
        if event.widget is not window:
            return
        button.lift()
        size = (event.width, event.height)
        if size == state["size"] or state["dragged"]:
            return
        state["size"] = size
        if state["pending"] is not None:
            window.after_cancel(state["pending"])
        state["pending"] = window.after(400, settle)  # once the window has its size and its content
    drag = {"from": None, "moved": False}

    def press(event) -> None:
        drag["from"] = (event.x_root, event.y_root, button.winfo_x(), button.winfo_y())
        drag["moved"] = False

    def move(event) -> None:
        if drag["from"] is None:
            return
        x0, y0, bx, by = drag["from"]
        dx, dy = event.x_root - x0, event.y_root - y0
        if abs(dx) + abs(dy) > 4:
            drag["moved"], state["dragged"] = True, True
            left = min(max(bx + dx, 4), window.winfo_width() - button.winfo_width() - 4)
            top = min(max(by + dy, 4), window.winfo_height() - button.winfo_height() - 4)
            # kept from the bottom right, so that it stays in its corner when the window is resized
            state["spot"] = ("se", 1.0, 1.0, left + button.winfo_width() - window.winfo_width(),
                             top + button.winfo_height() - window.winfo_height())
            put()

    def release(event) -> None:
        if not drag["moved"]:
            open_flow(window, title)
        drag["from"] = None

    button.bind("<ButtonPress-1>", press)
    button.bind("<B1-Motion>", move)
    button.bind("<ButtonRelease-1>", release)
    button.bind("<Enter>", lambda event: button.configure(background=lit, foreground=ink_on(lit)))
    button.bind("<Leave>", lambda event: button.configure(background=rest, foreground=ink_on(rest)))
    button.open = lambda: open_flow(window, title)  # hooks for the tests
    button.settle = settle
    window.after_idle(put)
    window.after(600, settle)
    window.bind("<Configure>", resized, add="+")

    def tab_changed(event) -> None:  # another tab, other controls in the corner: looked at again
        if state["dragged"]:
            return
        if state["pending"] is not None:
            window.after_cancel(state["pending"])
        state["pending"] = window.after(250, settle)
    window.bind("<<NotebookTabChanged>>", tab_changed, add="+")
    window._mme_flow_button = button
    return button
