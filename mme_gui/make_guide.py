# mme_gui/make_guide.py
"""“Make commands”: a window that explains every `make` command of the project — what it does, why and when to use
it, an example — and draws the flow of the whole project with them, from the setup to the end of every branch:
your own PDFs or papers from the web → the database → ranking, classification, ML datasets → the accuracy measured →
the release and the article.

Two tabs:
  - **Project flow**: the diagram. Every command is a box (a main step) or a small chip under its box (a variant:
    the window of the same step, a cathode run, its --help …). Click any of them: the panel on the right says what
    it does, why you would use it, and gives the command to copy.
  - **Every command**: the same explanations as a list, by stage, with a search box.

Every target of the Makefile is explained here (a test checks it), so the window never falls behind the Makefile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------------------------------------ the stages
# (key, title, what the stage is for, colour light, colour dark): the colours are the categorical slots of the
# validated palette; each stage is also named in words wherever its colour shows.
STAGES = (
    ("setup", "1 · Set up", "Install the program once, check it works, open it.", "#2a78d6", "#3987e5"),
    ("build", "2 · Build the database", "Turn papers — your own PDFs or legal copies found on the web — into tables.",
     "#eb6834", "#d95926"),
    ("use", "3 · Use the database", "Rank the materials, classify them, prepare datasets for machine learning.",
     "#1baf7a", "#199e70"),
    ("measure", "4 · Measure the accuracy", "How right is the extraction? From your database: annotate, score, compare.",
     "#6250d6", "#9085e9"),
    ("share", "5 · Share and publish", "From your database: the dataset for Zenodo, every figure of the article.",
     "#e34948", "#e66767"),
    ("care", "Look after the project", "Documentation, versions, tidying, each command's own help.",
     "#6b7280", "#9ba3ad"),
)
STAGE = {key: (title, about, light, dark) for key, title, about, light, dark in STAGES}


from LocalExtraction.gui.single import once


@dataclass(frozen=True)
class MakeCommand:
    target: str
    stage: str
    what: str
    why: str
    example: str = ""
    options: str = ""

    @property
    def command(self) -> str:
        return self.example or f"make {self.target}"


def _help(target: str, of: str) -> MakeCommand:
    return MakeCommand(target, "care", f"Prints every option of {of}, as its --help does.",
                       f"To see what {of} can do before running it, without opening the manual.")


COMMANDS: Tuple[MakeCommand, ...] = (
    # 1 · Set up
    MakeCommand("install", "setup", "Creates the virtual environment .venv/, installs the requirements, the program "
                "and the English language model (spaCy).",
                "The first command on a new computer: every other command runs inside .venv/, apart from the rest of "
                "your Python.", "make install"),
    MakeCommand("install-locked", "setup", "The same as make install, with the exact package versions of "
                "requirements.lock.",
                "To reproduce published results: the same versions give the same numbers. Reviewers use this one.",
                "make install-locked"),
    MakeCommand("test", "setup", "Runs every test of the project (about 900).",
                "After installing, after an update, before a release: a failing test tells you something is broken "
                "before your data does.", "make test FAST=1", "K=<words> TESTS=<files> VERBOSE=1 FAST=1 ARGS=…"),
    MakeCommand("demo", "setup", "Runs the worked example: two open-access papers through every step, into "
                "examples/output/.",
                "To see the whole pipeline work in a minute, and to check your installation gives the expected "
                "values.", "make demo"),
    MakeCommand("gui", "setup", "Opens the main window: one button per part of the pipeline.",
                "The easiest way to use everything: no option to remember, every step explained on screen.",
                "make gui", "GUI_OPTS=--install-app"),
    MakeCommand("app", "setup", "macOS: makes ~/Applications/MoukhlijMatExtract.app, which opens the main window with "
                "the program's own name and icon in the Dock.",
                "To start the program from the Dock or Spotlight like any app, without a terminal.", "make app"),
    # 2 · Build the database — your own PDFs
    MakeCommand("local", "build", "Extracts the PDFs of LocalExtraction/papers into a database "
                "(LocalExtraction/local_output): materials, activation energies, conductivities, diffusion "
                "coefficients, with the page and sentence of each value.",
                "When you already have the papers: put the PDFs in the folder and run it. Only new or changed PDFs are "
                "read again.", "make local WORKERS=4",
                "INPUT= OUTPUT= WORKERS= OFFLINE=1 REBUILD=1 DOMAIN=electrolyte|cathode|anode"),
    MakeCommand("local-gui", "build", "The local extraction in its window, with progress and the results.",
                "The same as make local, when you prefer to see the papers go by.", "make local-gui"),
    MakeCommand("local-rebuild", "build", "Extracts every PDF again; the present database is kept in "
                "previous_<date>/.",
                "After updating the program: the new rules apply to every paper, and the old results stay to compare.",
                "make local-rebuild"),
    MakeCommand("local-cathode", "build", "Extracts LocalExtraction/papers_cathode into output_cathode, with the "
                "cathode rules.", "Cathode papers kept apart from the electrolytes, each with its own database.",
                "make local-cathode"),
    MakeCommand("local-anode", "build", "Extracts LocalExtraction/papers_anode into output_anode, with the anode "
                "rules.", "Anode papers kept apart, in their own database.", "make local-anode"),
    # 2 · Build the database — from the web
    MakeCommand("web-check", "build", "Tests the setup of the web part: the network, the API keys, the folders.",
                "Before a long web run: a missing key or a blocked network is found in seconds, not after an hour.",
                "make web-check", "JOB= PROBE_DOI=<an Elsevier DOI>"),
    MakeCommand("doi", "build", "Asks the scholarly databases for the DOIs of papers matching the job's keywords and "
                "saves them in a DOI list.",
                "To build the list of papers to retrieve, from your keywords, before downloading anything.",
                "make doi COUNT=200 JOB=configs/garnet.yaml",
                "COUNT= JOB= MAX= OUT= REFRESH=1 NO_EXPAND=1 KEYWORDS='…'"),
    MakeCommand("web", "build", "The whole web run: search (keywords and DOIs), your review of the papers, the "
                "download of the legal open copies, the extraction into WebScraping/web_output_<job>.",
                "To build a database from the literature without collecting the PDFs yourself — only legal copies "
                "(open access, publisher APIs with your keys).", "make web JOB=configs/garnet.yaml",
                "JOB= OUTPUT= WORKERS= STAGE= YES=1 LIMIT= DOIS= REFRESH=1 REBUILD=1 SNOWBALL=1 UPDATE=1"),
    MakeCommand("web-gui", "build", "The web run in its window: the job, the review, the downloads, the results.",
                "The same as make web, step by step, with the papers to approve shown on screen.", "make web-gui"),
    MakeCommand("web-fetch", "build", "After the review: downloads what you approved, then extracts it.",
                "To continue a run you stopped after reviewing the papers.", "make web-fetch JOB=configs/garnet.yaml"),
    MakeCommand("web-extract", "build", "Only extracts the PDFs already downloaded.",
                "After adding PDFs by hand, or after updating the program (with REBUILD=1).",
                "make web-extract JOB=configs/garnet.yaml REBUILD=1"),
    MakeCommand("web-dois", "build", "Only the saved DOI list: checked, those on topic downloaded and extracted.",
                "When you have a DOI list (from make doi or from a colleague) and want exactly those papers.",
                "make web-dois DOIS=WebScraping/Fetch_DOIs/dois.csv"),
    MakeCommand("web-cathode", "build", "The whole web run for cathodes (configs/cathode.yaml → web_output_cathode).",
                "A cathode database from the literature, apart from the electrolytes.", "make web-cathode"),
    MakeCommand("web-anode", "build", "The whole web run for anodes (configs/anode.yaml → web_output_anode).",
                "An anode database from the literature.", "make web-anode"),
    MakeCommand("update", "build", "Every job run before, searched again for what was published since.",
                "To keep a database up to date: run it every month or so; only the new papers are downloaded.",
                "make update YES=1"),
    MakeCommand("coverage", "build", "How far each job's papers went — found, downloaded, extracted — by publisher, "
                "into WebScraping/coverage/.",
                "To see what is missing and why (paywalled, refused, not found), and to report it in the article.",
                "make coverage"),
    # 3 · Use the database
    MakeCommand("rank", "use", "Ranks the materials by activation energy and sorts them into classes (Superionic, "
                "Performant, Acceptable, Rejected), one ranking per transport component.",
                "To find the best candidates in the database, with the evidence behind each rank.",
                "make rank COMPONENT=bulk TOP=20",
                "SOURCE= OUT= CRITERIA= POLICY= ORIGIN= ATTRIBUTION= COMPONENT= ELEMENT= TOP= KIND= FORMAT= …"),
    MakeCommand("rank-gui", "use", "The ranking in its window, with the filters and the table.",
                "The same as make rank, when you want to try filters and look at the result at once.", "make rank-gui"),
    MakeCommand("rank-cathode", "use", "Ranks the cathode database with the cathode criteria.",
                "Cathodes are judged on other properties than electrolytes.", "make rank-cathode"),
    MakeCommand("rank-anode", "use", "Ranks the anode database with the anode criteria.",
                "Anodes have their own criteria too.", "make rank-anode"),
    MakeCommand("classify", "use", "Classifies the materials by crystal family (garnet, NASICON …) and chemical family "
                "(oxide, sulfide …), then by property, type and origin: one table per branch.",
                "To compare like with like — a garnet's bulk activation energy with other garnets' — and to make the "
                "families the ML datasets are built from.", "make classify FORCE=1", "SOURCE= OUT= FORCE=1"),
    MakeCommand("classify-gui", "use", "The classification in its window, with the tree of branches and the flow.",
                "To browse the families and open any branch's table.", "make classify-gui"),
    MakeCommand("ml-export", "use", "Prepares a dataset for machine learning — one family, one property, one type, one "
                "origin, quality filters — into “Ready for ML/”.",
                "To train a model on clean, comparable values, each measurement counted once, with a datasheet that "
                "says how it was made.", "make ml-export FAMILY=garnet TARGET=Ea COMPONENT=bulk ORIGIN=experimental",
                "FAMILY= TARGET= COMPONENT= ORIGIN= ATTRIBUTION= KIND= TEMPERATURE= KEEP_DUPLICATES=1 …"),
    MakeCommand("ml-gui", "use", "The ML datasets window: family → property → type → origin → filters → Generate.",
                "The same as make ml-export, step by step, with the number of values kept shown as you choose.",
                "make ml-gui"),
    # 4 · Measure the accuracy
    MakeCommand("eval-sheet", "measure", "Draws papers at random and writes the workbook to annotate "
                "(Evaluation/annotation.xlsx): every value extracted, to mark correct, partly or wrong, and a sheet "
                "for the values missed.",
                "The start of any accuracy figure: a journal will ask how often the extraction is right.",
                "make eval-sheet PAPERS=60", "SOURCE= PAPERS= SEED= OUT= FORCE=1 ALL_PAPERS=1"),
    MakeCommand("eval-score", "measure", "Precision, recall and F1 per property, with 95 % intervals, the errors and "
                "the calibration, from the annotated workbook.",
                "The accuracy of the extraction, to report — and to measure again after changing the program.",
                "make eval-score", "GOLD= SOURCE= OUT= SEED= PREDICTIONS='…'"),
    MakeCommand("eval-agree", "measure", "The agreement of two annotators who annotated copies of one workbook "
                "(Cohen's kappa).",
                "Shows the reference values do not depend on one person's judgement — reviewers ask for it.",
                "make eval-agree FIRST=a.xlsx SECOND=b.xlsx"),
    MakeCommand("eval-benchmark", "measure", "MoukhlijMatExtract against a keyword baseline and other tools "
                "(ChemDataExtractor, an LLM …) on the same annotated papers, with a table and a figure.",
                "A method paper must show it beats simpler methods and existing tools, on the same data.",
                "make eval-benchmark TOOL='ChemDataExtractor=cde.csv'",
                "GOLD= TOOL='NAME=file.csv …' NO_BASELINE=1 SOURCE= OUT= SEED="),
    MakeCommand("eval-gold", "measure", "Packages the annotated papers as a public gold-standard dataset: the values, "
                "the papers, the guide, the agreement, a datasheet, .zenodo.json.",
                "Others can score their tools on your reference set — a citable contribution of its own.",
                "make eval-gold SECOND=b.xlsx", "GOLD= SECOND= NAME= OUT="),
    MakeCommand("eval-reference", "measure", "Recall against curated databases (OBELiX, Liverpool), on their own "
                "papers.",
                "A second, independent accuracy figure that needs no annotation by hand.", "make eval-reference",
                "AGAINST= DB= NO_FETCH=1 LIMIT= REFRESH=1 WORKERS= PREDICTIONS="),
    # 5 · Share and publish
    MakeCommand("release", "share", "The databases, the ranking and the classification in one folder and .zip, "
                "licence-checked (only legal copies), with a datasheet and SHA256SUMS, into Release/.",
                "To deposit the dataset on Zenodo and cite it by DOI in the article.", "make release",
                "SOURCE= WITH= NO_RESULTS=1 OUT= KEEP_TEXT=1 FINISH="),
    MakeCommand("paper", "share", "Makes every table and figure of the article again from the data, with the "
                "environment recorded (environment.json) and RESULTS.md, into paper/.",
                "Reproducibility: a reviewer runs one command and gets your numbers. Run it before submitting.",
                "make paper", "DATA= GOLD= TOOL= OUT="),
    MakeCommand("paper-docker", "share", "The same as make paper, inside the pinned Docker image.",
                "The strongest reproducibility: the same operating system and packages on any computer.",
                "make paper-docker"),
    # Look after the project
    MakeCommand("lock", "care", "Writes requirements.lock: the exact package versions of this environment.",
                "Before a release: it freezes the environment your results were made with.", "make lock"),
    MakeCommand("commands", "care", "Rewrites docs/COMMANDS.md: every command with all of its options.",
                "After changing an option: the documentation stays exact.", "make commands"),
    MakeCommand("manual", "care", "Prints every command at a glance, with the typical runs (= mme help).",
                "A quick reminder in the terminal.", "make manual"),
    MakeCommand("dictionary", "care", "Rewrites docs/DATA_DICTIONARY.md: every column of the database.",
                "After changing the database's columns: what each column means stays documented.", "make dictionary"),
    MakeCommand("version", "care", "Prints the version of MoukhlijMatExtract.",
                "To cite the exact version, or to report a problem.", "make version"),
    MakeCommand("clean", "care", "Removes every __pycache__ folder.", "Tidying; harmless, nothing of yours is touched.",
                "make clean"),
    MakeCommand("help", "care", "Lists every make command with its options.", "The reference in the terminal.",
                "make help"),
    _help("gui-help", "the main window (mme-gui)"),
    _help("local-help", "the local extraction"),
    _help("local-gui-help", "the local extraction's window"),
    _help("web-help", "the web run"),
    _help("web-gui-help", "the web window"),
    _help("doi-help", "the DOI search"),
    _help("rank-help", "the ranking"),
    _help("rank-gui-help", "the ranking's window"),
    _help("classify-help", "the classification"),
    _help("classify-gui-help", "the classification's window"),
    _help("eval-help", "the evaluation commands"),
    _help("release-help", "the release"),
    _help("mme-help", "the mme command"),
)
BY_TARGET: Dict[str, MakeCommand] = {c.target: c for c in COMMANDS}

# ------------------------------------------------------------------------------------------------ the flow diagram
# The boxes: target -> (column, y); the columns are 0–3. Variants hang under their box as chips.
COLUMN_X, BOX_W, BOX_H = (30, 245, 460, 675), 195, 64
CHANNEL = 26  # the free strip on the right of a box's chips
WIDTH = 900
NODES: Dict[str, Tuple[int, int]] = {
    "install": (0, 70), "test": (1, 70), "demo": (2, 70), "gui": (3, 70),
    "local": (0, 285), "web-check": (1, 285), "doi": (2, 285), "web": (3, 285),
    "coverage": (1, 465), "update": (2, 465),
    "rank": (0, 690), "classify": (1, 690), "ml-export": (2, 690),
    "eval-sheet": (0, 900), "eval-score": (2, 900), "eval-benchmark": (3, 900),
    "eval-reference": (0, 1035), "eval-agree": (1, 1035), "eval-gold": (2, 1035),
    "release": (0, 1215), "paper": (2, 1215),
}
# What each box says under its command.
SHORT: Dict[str, str] = {
    "install": "the environment and the program", "test": "every test of the project", "demo": "the worked example",
    "gui": "the main window", "local": "your PDFs → a database", "web-check": "network, API keys, folders",
    "doi": "keywords → a list of DOIs", "web": "search · review · download · extract",
    "coverage": "how far the papers went", "update": "what was published since",
    "rank": "the best materials, by Ea", "classify": "families → property → type",
    "ml-export": "a clean dataset for ML", "eval-sheet": "papers drawn → a workbook",
    "eval-score": "precision · recall · F1", "eval-benchmark": "MME vs baseline and tools",
    "eval-reference": "recall vs curated databases", "eval-agree": "two annotators: kappa",
    "eval-gold": "the public gold standard", "release": "the dataset, licence-checked",
    "paper": "every table and figure",
}
CHIPS: Dict[str, Tuple[str, ...]] = {
    "install": ("install-locked", "lock"), "gui": ("app",),
    "local": ("local-gui", "local-rebuild", "local-cathode", "local-anode"),
    "web": ("web-gui", "web-fetch", "web-extract", "web-dois", "web-cathode", "web-anode"),
    "rank": ("rank-gui", "rank-cathode", "rank-anode"),
    "classify": ("classify-gui",), "ml-export": ("ml-gui",), "paper": ("paper-docker",),
}
# Steps that are not commands: what you do by hand, and what the commands make.
PLACES: Dict[str, Tuple[int, int, int, str, str]] = {  # key -> (column, last column, y, title, line)
    "database": (0, 3, 575, "Your database",
                 "LocalExtraction/local_output · WebScraping/web_output_<job> — one table per property"),
    "annotate": (1, 1, 900, "You annotate", "mark each value correct, partly or wrong; add the missed ones"),
    "zenodo": (1, 1, 1215, "Zenodo deposit", "the dataset and the gold standard, citable by DOI"),
    "article": (3, 3, 1215, "The article", "every number reproducible"),
}
EDGES: Tuple[Tuple[str, str], ...] = (
    ("install", "test"), ("test", "demo"), ("demo", "gui"),
    ("gui", "local"), ("gui", "web-check"), ("web-check", "doi"), ("doi", "web"),
    ("local", "database"), ("update", "database"), ("web", "database"),
    ("database", "rank"), ("database", "classify"), ("classify", "ml-export"),
    ("eval-sheet", "annotate"), ("annotate", "eval-score"),
    ("eval-score", "eval-benchmark"), ("annotate", "eval-agree"), ("annotate", "eval-gold"),
    ("eval-gold", "zenodo"), ("release", "zenodo"), ("paper", "article"), ("eval-benchmark", "article"),
)
LANES = (("setup", 22, 205), ("build", 222, 640), ("use", 658, 840), ("measure", 858, 1150), ("share", 1168, 1330))
CARE = ("commands", "manual", "dictionary", "version", "clean", "help")
HELPS = ("gui-help", "local-help", "local-gui-help", "web-help", "web-gui-help", "doi-help", "rank-help",
         "rank-gui-help", "classify-help", "classify-gui-help", "eval-help", "release-help", "mme-help")
CARE_TOP = 1348
HEIGHT = 1540


def in_diagram() -> List[str]:
    """Every target the diagram shows, as a box or a chip."""
    return list(NODES) + [t for chips in CHIPS.values() for t in chips] + list(CARE) + list(HELPS)


def _rounded(canvas, x1, y1, x2, y2, r, **options):
    points = (x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2,
              x1, y2 - r, x1, y1 + r, x1, y1)
    return canvas.create_polygon(points, smooth=True, splinesteps=12, **options)


class FlowDiagram:
    """The project's flow on a canvas; clicking a box or a chip calls `on_pick(target)`."""

    def __init__(self, canvas, colours: Dict[str, str], dark: bool, on_pick):
        self.canvas, self.c, self.dark, self.on_pick = canvas, colours, dark, on_pick
        self.items: Dict[str, int] = {}     # target -> its outline item (to show which is chosen)
        self.edges_of: Dict[str, str] = {}  # target -> its outline colour at rest
        self.anchors: Dict[str, Tuple[float, float, float, float]] = {}  # target or place -> its rectangle
        self.texts: List[str] = []          # every word drawn (for the tests)
        self.chosen: Optional[str] = None
        self.draw()

    def colour(self, stage: str) -> str:
        return STAGE[stage][3 if self.dark else 2]

    def text(self, x, y, words, **options):
        self.texts.append(words)
        return self.canvas.create_text(x, y, text=words, **options)

    # ---------------------------------------------------------------- the parts
    def lane(self, stage: str, top: float, bottom: float) -> None:
        _rounded(self.canvas, 12, top, WIDTH - 12, bottom, 18, fill=self.c["stripe"], outline="")

    def lane_title(self, stage: str, top: float) -> None:
        """The stage's name and purpose, over the arrows that pass under it."""
        cv, c = self.canvas, self.c
        title, about, *_ = STAGE[stage]
        dot = cv.create_oval(26, top + 14, 38, top + 26, fill=self.colour(stage), outline="")
        name = self.label(46, top + 20, title, c["ink"], ("TkDefaultFont", 13, "bold"))
        x = cv.bbox(name)[2] + 18
        self.label(x, top + 20, about, c["muted"], ("TkDefaultFont", 10))
        cv.tag_raise(dot)

    def label(self, x, y, words, ink, font):
        """Words on the lane's colour: an arrow passing there goes under them."""
        item = self.text(x, y, words, anchor="w", fill=ink, font=font)
        x1, y1, x2, y2 = self.canvas.bbox(item)
        back = self.canvas.create_rectangle(x1 - 4, y1 - 1, x2 + 4, y2 + 1, fill=self.c["stripe"], outline="")
        self.canvas.tag_raise(item, back)
        return item

    def box(self, target: str, column: int, y: float) -> None:
        cv, c = self.canvas, self.c
        command = BY_TARGET[target]
        x = COLUMN_X[column]
        tag = f"t:{target}"
        shadow = "#0b0b0b" if self.dark else "#dfe3ea"
        _rounded(cv, x + 2, y + 3, x + BOX_W + 2, y + BOX_H + 3, 12, fill=shadow, outline="")
        outline = _rounded(cv, x, y, x + BOX_W, y + BOX_H, 12, fill=c["card"], outline=c["line"], width=1, tags=tag)
        cv.create_rectangle(x + 1, y + 10, x + 6, y + BOX_H - 10, fill=self.colour(command.stage), outline="",
                            tags=tag)
        from .manual import mono
        self.text(x + 18, y + 22, f"make {target}", anchor="w", fill=c["ink"], font=mono(12, "bold"), tags=tag)
        self.text(x + 18, y + 44, SHORT.get(target) or _short(command.what), anchor="w", fill=c["muted"],
                  font=("TkDefaultFont", 10), width=BOX_W - 26, tags=tag)
        self.items[target] = outline
        self.anchors[target] = (x, y, x + BOX_W, y + BOX_H)
        self._clickable(tag, target)

    def chips(self, parent: str) -> None:
        from tkinter import font as tkfont

        from .manual import mono
        x0, y0, x1, y1 = self.anchors[parent]
        x, y = x0, y1 + 10
        measure = tkfont.Font(font=mono(10)).measure
        for target in CHIPS.get(parent, ()):
            if x > x0 and x + measure(target) + 22 > x1 - CHANNEL:  # the right edge stays free for the arrow
                x, y = x0, y + 26
            x += self.pill(target, x, y, target, 10, 21, self.colour(BY_TARGET[target].stage)) + 6

    def place(self, key: str, first: int, last: int, y: float, title: str, line: str) -> None:
        cv, c = self.canvas, self.c
        x0, x1 = COLUMN_X[first], COLUMN_X[last] + BOX_W
        _rounded(cv, x0, y, x1, y + BOX_H - 8, 12, fill=c["selected"], outline=c["accent"], width=1, dash=(4, 3))
        self.text(x0 + 16, y + 18, title, anchor="w", fill=c["ink"], font=("TkDefaultFont", 12, "bold"))
        self.text(x0 + 16, y + 38, line, anchor="w", fill=c["muted"], font=("TkDefaultFont", 10),
                  width=x1 - x0 - 26)
        self.anchors[key] = (x0, y, x1, y + BOX_H - 8)

    def edge(self, a: str, b: str) -> None:
        ax0, ay0, ax1, ay1 = self.anchors[a]
        bx0, by0, bx1, by1 = self.anchors[b]
        colour, cv = self.c["accent"], self.canvas
        line = {"fill": colour, "width": 2, "arrow": "last", "arrowshape": (9, 11, 4)}
        if abs(ay0 - by0) < 5:   # side by side: left to right
            cv.create_line(ax1, (ay0 + ay1) / 2, bx0, (by0 + by1) / 2, **line)
            return
        if ax1 - ax0 > bx1 - bx0 + 10:   # from a wide place to a box: straight down to its middle
            x = (bx0 + bx1) / 2
            cv.create_line(x, ay1, x, by0, **line)
            return
        # from a box: out by its free channel when chips hang under it, else its middle
        start = ax1 - CHANNEL / 2 if a in CHIPS else (ax0 + ax1) / 2
        if bx1 - bx0 > ax1 - ax0 + 10:   # into a wide place: straight down
            cv.create_line(start, ay1, start, by0, **line)
            return
        end = (bx0 + bx1) / 2
        if abs(start - end) < 2:
            cv.create_line(start, ay1, end, by0, **line)
            return
        turn = self.gap_below(ay1, by0)
        cv.create_line(start, ay1, start, turn, end, turn, end, by0, **line)

    @staticmethod
    def gap_below(top: float, bottom: float) -> float:
        """Where a downward arrow turns: in the gap between two lanes when it crosses one, else just above its end."""
        for _, lane_top, lane_bottom in LANES:
            if top < lane_bottom < bottom:
                return lane_bottom + 8
        return bottom - 14

    def pill(self, target: str, x: float, y: float, words: str, size: int, height: float, outline: str) -> float:
        """A clickable chip; returns its width."""
        from tkinter import font as tkfont

        from .manual import mono
        width = tkfont.Font(font=mono(size)).measure(words) + 22
        tag = f"t:{target}"
        item = _rounded(self.canvas, x, y, x + width, y + height, min(12, height / 2), fill=self.c["card"],
                        outline=outline, width=1, tags=tag)
        self.text(x + width / 2, y + height / 2, words, fill=self.c["ink"], font=mono(size), tags=tag)
        self.items[target] = item
        self.edges_of[target] = outline
        self._clickable(tag, target)
        return width

    def care(self) -> None:
        cv, c = self.canvas, self.c
        top = CARE_TOP
        _rounded(cv, 12, top, WIDTH - 12, HEIGHT - 14, 18, fill=c["stripe"], outline="")
        title, about, *_ = STAGE["care"]
        cv.create_oval(26, top + 14, 38, top + 26, fill=self.colour("care"), outline="")
        name = self.label(46, top + 20, title, c["ink"], ("TkDefaultFont", 13, "bold"))
        self.label(cv.bbox(name)[2] + 18, top + 20, "any time — " + about[0].lower() + about[1:], c["muted"],
                   ("TkDefaultFont", 10))
        x, y = 30, top + 44
        for target in CARE:
            x += self.pill(target, x, y, f"make {target}", 11, 32, c["line"]) + 10
        y += 50
        self.label(30, y + 10, "Each part's own help (its options, as --help prints them):", c["muted"],
                   ("TkDefaultFont", 10))
        x, y = 30, y + 26
        for target in HELPS:
            from tkinter import font as tkfont

            from .manual import mono
            if x + tkfont.Font(font=mono(10)).measure(target) + 22 > WIDTH - 30:
                x, y = 30, y + 28
            x += self.pill(target, x, y, target, 10, 22, self.colour("care")) + 6

    # ---------------------------------------------------------------- drawing, choosing
    def draw(self) -> None:
        for stage, top, bottom in LANES:
            self.lane(stage, top, bottom)
        for key, (first, last, y, title, line) in PLACES.items():
            self.place(key, first, last, y, title, line)
        for target, (column, y) in NODES.items():
            self.box(target, column, y)
        for a, b in EDGES:
            self.edge(a, b)
        for parent in CHIPS:
            self.chips(parent)
        for stage, top, _ in LANES:
            self.lane_title(stage, top)
        quiet, italic = self.c["muted"], ("TkDefaultFont", 10, "italic")
        self.label(COLUMN_X[0], 262, "Your own PDFs", quiet, italic)
        self.label(COLUMN_X[1], 262, "or papers from the web (legal copies only)", quiet, italic)
        self.label(COLUMN_X[1], 450, "after a web run, now and then:", quiet, italic)
        self.care()
        for target in self.items:
            self.canvas.tag_raise(f"t:{target}")

    def _clickable(self, tag: str, target: str) -> None:
        cv = self.canvas
        cv.tag_bind(tag, "<Button-1>", lambda event: self.choose(target, tell=True))
        cv.tag_bind(tag, "<Enter>", lambda event: (cv.configure(cursor="hand2"), self._hover(target, True)))
        cv.tag_bind(tag, "<Leave>", lambda event: (cv.configure(cursor=""), self._hover(target, False)))

    def _hover(self, target: str, inside: bool) -> None:
        if target != self.chosen:
            self.canvas.itemconfigure(self.items[target], width=2 if inside else 1)

    def choose(self, target: str, tell: bool = False) -> None:
        if self.chosen in self.items:
            old = self.chosen
            self.canvas.itemconfigure(self.items[old], width=1, outline=self._outline(old))
        self.chosen = target
        self.canvas.itemconfigure(self.items[target], width=3, outline=self.c["accent"])
        if tell:
            self.on_pick(target)

    def _outline(self, target: str) -> str:
        return self.edges_of.get(target, self.c["line"])


def ink_on(colour: str) -> str:
    """White or near-black, whichever reads better on this background (WCAG contrast)."""
    colour = colour.lstrip("#")
    channels = [int(colour[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    light = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#ffffff" if (1.05 / (light + 0.05)) >= ((light + 0.05) / 0.05) else "#0b0b0b"


def _short(text: str, limit: int = 58) -> str:
    first = text.split(":")[0].split(" — ")[0].split(", ")[0].rstrip(".")
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


# ------------------------------------------------------------------------------------------------ the window
INTRO = ("Click any box or chip of the diagram: what the command does, why you would use it, and the command to "
         "copy appear here.\n\nThe flow runs top to bottom: set up once → build the database (your PDFs, or papers "
         "from the web) → use it → measure how accurate it is → share it and publish.\n\nEvery command is typed in a "
         "terminal, in the project's folder. The main window's buttons run the same steps.")


@once("make-commands", "The Make commands window")
def open_make_guide(parent) -> "object":
    """The window. Returns it; `.diagram`, `.show(target)` and `.listing` are hooks for the tests."""
    import tkinter as tk
    from tkinter import ttk

    from LocalExtraction.gui import design, layout, theme
    from LocalExtraction.gui.widgets import WrapLabel

    from .manual import mono

    win = tk.Toplevel(parent)
    win.title("MoukhlijMatExtract · Make commands")
    layout.place(win, (1320, 900), (900, 600), parent=parent)
    theme.apply(win)
    colours, dark = theme.palette(win), theme.is_dark(win)
    design.header(win, "Make commands", "every command of the project — what it does, why to use it — and the flow of "
                  "the whole project", compact=True)
    tabs = ttk.Notebook(win)
    tabs.pack(fill="both", expand=True, padx=14, pady=(10, 0))

    # ---- tab 1: the flow and the panel
    flow = ttk.Frame(tabs)
    tabs.add(flow, text="  Project flow  ")
    left = ttk.Frame(flow)
    left.pack(side="left", fill="both", expand=True)
    canvas = tk.Canvas(left, width=WIDTH, background=colours["card"], highlightthickness=0,
                       scrollregion=(0, 0, WIDTH, HEIGHT))
    bar = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    panel = ttk.Frame(flow, padding=(18, 14, 14, 14), width=360)
    panel.pack(side="right", fill="y")
    panel.pack_propagate(False)
    stage_line = tk.Label(panel, text="How to read the diagram", font=("TkDefaultFont", 10, "bold"),
                          fg=ink_on(colours["accent"]), background=colours["accent"], padx=8, pady=2)
    stage_line.pack(anchor="w")
    title = ttk.Label(panel, text="", font=mono(15, "bold"))
    title.pack(anchor="w", pady=(10, 4))
    sections = {}
    for key, heading in (("what", "What it does"), ("why", "Why use it"), ("options", "Options (NAME=value)")):
        head = ttk.Label(panel, text=heading, style="Section.TLabel")
        body = WrapLabel(panel, text="", wraplength=320)
        sections[key] = (head, body)
    intro = WrapLabel(panel, text=INTRO, wraplength=320)
    intro.pack(anchor="w", fill="x")
    example_head = ttk.Label(panel, text="Type it", style="Section.TLabel")
    example_row = ttk.Frame(panel)
    example = tk.Label(example_row, text="", font=mono(11), anchor="w", justify="left", wraplength=320,
                       background=colours["stripe"], foreground=colours["ink"], padx=8, pady=6)
    example.pack(fill="x")
    copied = ttk.Label(example_row, text="", style="Muted.TLabel")

    def copy() -> None:
        win.clipboard_clear()
        win.clipboard_append(example.cget("text"))
        copied.configure(text="Copied — paste it in a terminal, in the project's folder.")
    copy_button = ttk.Button(example_row, text="Copy the command", command=copy)
    copy_button.pack(anchor="w", pady=(6, 0))
    copied.pack(anchor="w", pady=(4, 0))

    def show(target: str) -> None:
        command = BY_TARGET[target]
        stage_title, _, light, darker = STAGE[command.stage]
        badge = darker if dark else light
        stage_line.configure(text=stage_title, background=badge, foreground=ink_on(badge))
        title.configure(text=f"make {target}")
        intro.pack_forget()
        for key, (head, body) in sections.items():
            head.pack_forget()
            body.pack_forget()
        example_head.pack_forget()
        example_row.pack_forget()
        for key, (head, body) in sections.items():
            words = getattr(command, key)
            if words:
                body.configure(text=words)
                head.pack(anchor="w", pady=(10, 2))
                body.pack(anchor="w", fill="x")
        example.configure(text=command.command)
        copied.configure(text="")
        example_head.pack(anchor="w", pady=(12, 4))
        example_row.pack(anchor="w", fill="x")
        diagram.choose(target)
        win.chosen = target

    diagram = FlowDiagram(canvas, colours, dark, show)

    def wheel(event) -> None:
        if event.num == 4 or getattr(event, "delta", 0) > 0:
            canvas.yview_scroll(-1 if event.num == 4 or abs(event.delta) < 120 else -int(event.delta / 120), "units")
        else:
            canvas.yview_scroll(1 if event.num == 5 or abs(event.delta) < 120 else int(-event.delta / 120), "units")
    canvas.bind("<Enter>", lambda event: (canvas.bind_all("<MouseWheel>", wheel), canvas.bind_all("<Button-4>", wheel),
                                          canvas.bind_all("<Button-5>", wheel)))
    canvas.bind("<Leave>", lambda event: (canvas.unbind_all("<MouseWheel>"), canvas.unbind_all("<Button-4>"),
                                          canvas.unbind_all("<Button-5>")))

    # ---- tab 2: every command, by stage, with a search
    listing_tab = ttk.Frame(tabs, padding=(4, 10, 4, 4))
    tabs.add(listing_tab, text="  Every command  ")
    search_row = ttk.Frame(listing_tab)
    search_row.pack(fill="x", pady=(0, 8))
    ttk.Label(search_row, text="Find:").pack(side="left")
    wanted = tk.StringVar()
    ttk.Entry(search_row, textvariable=wanted, width=40).pack(side="left", padx=8)
    found_label = ttk.Label(search_row, text="", style="Muted.TLabel")
    found_label.pack(side="left")
    text = tk.Text(listing_tab, wrap="word", padx=18, pady=10, relief="flat", font=("TkDefaultFont", 11),
                   background=colours["card"], foreground=colours["ink"], cursor="arrow")
    text_bar = ttk.Scrollbar(listing_tab, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=text_bar.set)
    text_bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    text.tag_configure("stage", font=("TkDefaultFont", 15, "bold"), foreground=colours["accent"], spacing1=16,
                       spacing3=2)
    text.tag_configure("about", foreground=colours["muted"], spacing3=8)
    text.tag_configure("cmd", font=mono(12, "bold"), spacing1=10, foreground=colours["ink"])
    text.tag_configure("label", font=("TkDefaultFont", 11, "bold"), lmargin1=20, lmargin2=20)
    text.tag_configure("body", lmargin1=20, lmargin2=20, spacing3=1)
    text.tag_configure("example", font=mono(11), lmargin1=20, lmargin2=20, foreground=colours["garnet"], spacing3=4)
    for key, _, _, light, darker in STAGES:
        text.tag_configure(f"dot:{key}", foreground=darker if dark else light)

    def fill(*args) -> None:
        words = wanted.get().strip().lower()
        text.configure(state="normal")
        text.delete("1.0", "end")
        shown = 0
        for key, stage_title, about, *_ in STAGES:
            mine = [c for c in COMMANDS if c.stage == key and (not words or words in
                                                                (c.target + " " + c.what + " " + c.why).lower())]
            if not mine:
                continue
            text.insert("end", "● ", f"dot:{key}")
            text.insert("end", stage_title + "\n", "stage")
            text.insert("end", about + "\n", "about")
            for command in mine:
                shown += 1
                text.insert("end", f"make {command.target}\n", "cmd")
                text.insert("end", "What: ", "label")
                text.insert("end", command.what + "\n", "body")
                text.insert("end", "Why: ", "label")
                text.insert("end", command.why + "\n", "body")
                if command.options:
                    text.insert("end", "Options: ", "label")
                    text.insert("end", command.options + "\n", "body")
                text.insert("end", "$ " + command.command + "\n", "example")
        found_label.configure(text=f"{shown} of {len(COMMANDS)} commands")
        text.configure(state="disabled")
    wanted.trace_add("write", fill)
    fill()

    footer = ttk.Frame(win, padding=(14, 8))
    footer.pack(fill="x")
    ttk.Label(footer, style="Muted.TLabel",
              text="make help lists them all in a terminal; NAME=value after a command sets an option.").pack(side="left")
    design.back_button(footer, win).pack(side="right")
    design.website_line(win)
    win.bind("<Escape>", lambda event: design.go_back(win))
    win.diagram, win.show, win.listing, win.search, win.tabs = diagram, show, text, wanted, tabs
    win.chosen = None
    return win


def add_make_button(parent, root):
    """The “Make commands” button of the main window. `widget.open()` opens the window (the tests use it)."""
    import tkinter as tk

    colour = "#0f766e"
    button = tk.Label(parent, text="⚙ Make commands", cursor="hand2", font=("TkDefaultFont", 11, "bold"), fg="white",
                      background=colour, padx=12, pady=4, relief="raised", bd=1)

    def open_it(event=None):
        return open_make_guide(root)

    button.bind("<Button-1>", open_it)
    button.open = open_it
    from LocalExtraction.gui.theme import label_hover
    label_hover(button, lambda: colour)
    return button
