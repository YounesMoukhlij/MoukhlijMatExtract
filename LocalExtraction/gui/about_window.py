# LocalExtraction/gui/about_window.py
"""“About & methods”: what a reader of a paper made with MoukhlijMatExtract needs to know of it — the software and
how to cite it, what it does step by step, the rules it keeps on sources and records, the accuracy measured on
this computer (never a figure that was not measured), and the environment it runs in, ready to be copied into the
Methods section of a paper. Everything shown is read from the program itself: its version, its commit, the
environment a run records (provenance.environment), CITATION.cff and the evaluations scored here."""

from __future__ import annotations

import json
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

from . import design, theme

ROOT = Path(__file__).resolve().parents[2]  # the project folder (or site-packages)

METHOD = (
    ("Search", "Keyword queries of a job file are asked of up to 25 bibliographic sources (OpenAlex, Crossref, "
               "Semantic Scholar, arXiv, Europe PMC, OpenAIRE, CORE, Scopus, …), with a DOI list collected first; "
               "records are deduplicated by DOI and by normalised title (a preprint and its journal version count once)."),
    ("Screening", "Each record is scored on its title (2 points per word) and abstract (1 point): it needs a topic word "
                  "(the material family) and a property word (what is measured); an excluded word costs 3 points. "
                  "Formulas are found however they are written, and a family's formula part finds its doped members."),
    ("Legal retrieval", "Only lawful copies: the publishers' text-and-data-mining interfaces, the open-access locations "
                        "indexed by OpenAlex and Unpaywall, repositories (PMC, arXiv, OSTI, HAL, Zenodo, CORE, …). A "
                        "file is kept only if it opens as a PDF, has two pages or more (or at least 1,500 characters), "
                        "and its first three pages carry at least half of the title's words — checked when they hold "
                        "800 characters of text or more (a scan without text is kept unchecked)."),
    ("Extraction", "Text is read with PyMuPDF and pdfplumber (Tesseract OCR for image-only pages); sentences are parsed "
                   "with spaCy, and rules find activation energies, conductivities and diffusion coefficients with "
                   "their units, converted with pint. Each value keeps its material, the rule that tied it to it, its "
                   "kind (Arrhenius, computed barrier, …), component, origin, attribution, sentence and page."),
    ("Ranking", "Per material and transport component, the confidence-weighted median of its values; classes from "
                "criteria.toml. Filters choose the values (origin, attribution, kind of energy, component, elements)."),
    ("Evaluation", "Precision, recall and F1 against a person's annotation of papers drawn at random, with 95 % "
                   "bootstrap intervals over papers (mme-eval; docs/EVALUATION_PROTOCOL.md)."),
)

INTEGRITY = (
    "Sources: open access and publishers' licensed interfaces only. robots.txt, HTTP 401/403 and rate limits are "
    "respected; nothing gets around a refusal (no browser disguise, proxy or address rotation).",
    "Requests: each host is spaced; a site that answers “too many requests” is asked less often for the rest of the run.",
    "Provenance: every PDF has a record beside it — source, URL, licence, retrieval date and SHA-256 checksum.",
    "Records of runs: each extraction, ranking, classification and evaluation adds to run_manifest.json its "
    "settings, the software versions and the checksum of every file it wrote.",
    "Release: a published dataset leaves out every paper whose source is not recorded or not lawful.",
)


def citation() -> Tuple[str, str]:
    """(the citation in words, its BibTeX), from CITATION.cff when the project folder is there."""
    from ..about import AUTHOR, FULL_NAME, REPOSITORY, version
    data: Dict = {}
    path = ROOT / "CITATION.cff"
    if path.exists():
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    authors = data.get("authors") or [{"family-names": AUTHOR.split()[-1], "given-names": " ".join(AUTHOR.split()[:-1])}]
    names = ", ".join(f"{a.get('family-names', '')}, {a.get('given-names', '')[:1]}." for a in authors)
    number = version() or data.get("version", "")
    year = str(data.get("date-released", ""))[:4]
    title = data.get("title", FULL_NAME)
    url = data.get("repository-code") or REPOSITORY
    doi = data.get("doi", "")
    text = (f"{names} ({year or 'n.d.'}). {title} (Version {number}) [Computer software]. "
            + (f"https://doi.org/{doi}" if doi else url))
    people = " and ".join(f"{a.get('family-names', '')}, {a.get('given-names', '')}" for a in authors)
    fields = [("author", people), ("title", title), ("version", number), ("year", year), ("doi", doi), ("url", url)]
    bibtex = "@software{moukhlijmatextract,\n" + ",\n".join(
        f"  {name:<7} = {{{value}}}" for name, value in fields if value) + "\n}"
    return text, bibtex


def measured_accuracy(folder: Optional[Path] = None) -> List[str]:
    """One line per evaluation scored on this computer (Evaluation/scores*/metrics.json): papers checked, and the
    precision and recall of the right value for the right material, with their 95 % intervals."""
    if folder is None:
        from Evaluation.about import DEFAULT_DIR as folder
    lines = []
    for path in sorted(Path(folder).glob("scores*/metrics.json")):
        try:
            metrics = json.loads(path.read_text(encoding="utf-8"))
            record = metrics["levels"]["record"]["all"]
        except (OSError, ValueError, KeyError):
            continue

        def pct(name: str) -> str:
            value, ci = record.get(name), (record.get("ci95") or {}).get(name)
            if value is None:
                return "–"
            return f"{100 * value:.0f} %" + (f" (95 % CI {100 * ci[0]:.0f}–{100 * ci[1]:.0f} %)" if ci else "")
        lines.append(f"{path.parent.name}: {metrics.get('papers', '?')} papers, {metrics.get('gold', '?')} reference "
                     f"values — precision {pct('precision')}, recall {pct('recall')} (right value, right material)")
    return lines


def environment_text(env: Dict) -> str:
    """The environment, as a paragraph for a Methods section."""
    packages = ", ".join(f"{name} {number}" for name, number in sorted((env.get("packages") or {}).items()))
    git = env.get("git") or {}
    commit = (f", commit {git.get('commit', '')[:10]}" + (" (with changes not committed)" if git.get("dirty") else "")
              if git.get("commit") else "")
    return (f"{env.get('software', '')}{commit}; Python {env.get('python', '')} on {env.get('platform', '')}; "
            f"language model {env.get('language_model', 'not loaded')}; Tesseract {env.get('tesseract', '')}; "
            f"packages: {packages}.")


def open_about(parent: tk.Misc) -> tk.Toplevel:
    from ..about import ABOUT_AUTHOR, LICENSE_NAME, REPOSITORY, WEBSITE, version
    colours = theme.palette(parent)
    window = tk.Toplevel(parent)
    window.title("MoukhlijMatExtract · About & methods")
    from . import layout
    layout.place(window, (880, 760), (680, 520), parent=parent)  # fitted to the screen, over the window it is from
    window.bind("<Escape>", lambda event: window.destroy())
    theme.apply(window)
    design.header(window, "About & methods", "what the program does, the rules it keeps, and how to cite it")

    buttons = ttk.Frame(window, padding=(12, 8))
    buttons.pack(side="bottom", fill="x")
    body = ttk.Frame(window)
    body.pack(fill="both", expand=True)
    design.website_line(window)
    text = tk.Text(body, wrap="word", padx=20, pady=12, relief="flat", font=("TkDefaultFont", 11), cursor="arrow")
    bar = ttk.Scrollbar(body, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=bar.set)
    text.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    text.tag_configure("h", font=("TkDefaultFont", 14, "bold"), foreground=colours["accent"], spacing1=14, spacing3=6)
    text.tag_configure("step", font=("TkDefaultFont", 11, "bold"))
    text.tag_configure("item", lmargin1=16, lmargin2=34, spacing3=4)
    text.tag_configure("muted", foreground=colours["muted"])
    text.tag_configure("mono", font=("TkFixedFont", 10), lmargin1=16, lmargin2=16)

    cited, bibtex = citation()
    number = version()
    text.insert("end", "Software\n", "h")
    text.insert("end", f"MoukhlijMatExtract (MME){f' v{number}' if number else ''} · {LICENSE_NAME} · {REPOSITORY}\n", "item")
    text.insert("end", f"Website — how to use it, and an overview of the project: {WEBSITE}\n", "item")
    text.insert("end", ABOUT_AUTHOR + "\n", ("item", "muted"))
    text.insert("end", "How to cite\n", "h")
    text.insert("end", cited + "\n\n", "item")
    text.insert("end", bibtex + "\n", "mono")
    text.insert("end", "Method\n", "h")
    for index, (step, what) in enumerate(METHOD, 1):
        text.insert("end", f"{index}. {step}. ", ("item", "step"))
        text.insert("end", what + "\n", "item")
    text.insert("end", "Sources, records and research ethics\n", "h")
    for line in INTEGRITY:
        text.insert("end", f"•  {line}\n", "item")
    text.insert("end", "Accuracy measured on this computer\n", "h")
    lines = measured_accuracy()
    if lines:
        for line in lines:
            text.insert("end", f"•  {line}\n", "item")
        text.insert("end", "A figure holds for the papers and the protocol it was measured on; report it with its "
                           "interval.\n", ("item", "muted"))
    else:
        text.insert("end", "No evaluation has been scored on this computer yet, so no accuracy is claimed here. Measure it "
                           "with “Evaluate…” in windows 1 and 2 (mme-eval), following a protocol fixed before the "
                           "papers are drawn (docs/EVALUATION_PROTOCOL.md).\n", "item")
    text.insert("end", "Environment\n", "h")
    text.insert("end", "Reading the versions (the language model takes a moment to load) …\n", ("item", "muted"))
    text.mark_set("environment", "end-2l")
    text.mark_gravity("environment", "left")
    text.configure(state="disabled")
    window.environment = ""

    def copy(content: str) -> None:
        window.clipboard_clear()
        window.clipboard_append(content)

    ttk.Button(buttons, text="Copy the citation", command=lambda: copy(f"{cited}\n\n{bibtex}")).pack(side="left")
    environment_button = ttk.Button(buttons, text="Copy the environment (for a Methods section)", state="disabled",
                                    command=lambda: copy(window.environment))
    environment_button.pack(side="left", padx=6)
    ttk.Button(buttons, text="Open the repository", command=lambda: webbrowser.open(REPOSITORY)).pack(side="left")
    ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")

    found: List[str] = []

    def read() -> None:
        try:
            from ..provenance import environment
            found.append(environment_text(environment(with_model=True)))
        except Exception as error:  # the window says it, it does not fail
            found.append(f"The environment could not be read: {type(error).__name__}: {error}")

    def show() -> None:
        try:
            if not window.winfo_exists():
                return
        except tk.TclError:
            return
        if not found:
            window.after(150, show)
            return
        window.environment = found[0]
        text.configure(state="normal")
        text.delete("environment", "end")
        text.insert("end", "\n" + found[0] + "\n", "item")
        text.configure(state="disabled")
        environment_button.configure(state="normal")

    threading.Thread(target=read, name="about-environment", daemon=True).start()
    window.after(150, show)
    return window
