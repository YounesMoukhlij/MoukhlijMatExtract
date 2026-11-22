# Evaluation/benchmark.py
"""mme-eval benchmark: MoukhlijMatExtract against other methods, on the same papers annotated by a person.

Systems compared:
  - MoukhlijMatExtract: the values of the workbook (the run it was made from), or those now in --source;
  - the keyword baseline (baseline.py): a floor, unless --no-baseline;
  - every other tool given with --tool NAME=FILE.csv: its values for the same papers, in the columns paper_id,
    property, material, value (unit, component, origin, confidence optional) — ChemDataExtractor's, an LLM's …

Written to Evaluation/benchmark/ (or --out):
  - benchmark.md       the systems side by side (precision, recall, F1 with 95 % intervals, record and value level,
                       all properties and each one), how MoukhlijMatExtract differs from each (paired bootstrap)
  - benchmark.csv      every number of those tables, one row per system × property × level
  - benchmark.png      F1 (and precision, recall) of each system with its 95 % interval
  - baseline_predictions.csv   what the baseline found, to inspect
  - run_manifest.json  the settings, the software, the files

The papers are the workbook's papers marked done; the intervals resample whole papers (seed fixed)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from LocalExtraction.about import version
from LocalExtraction.provenance import Run

from . import baseline
from .about import PROPERTIES
from .score import (AnnotationError, Item, comparison_text, evaluate, extracted_from_databases, paired_difference,
                    predictions_from_csv, read_annotation)

OURS = "MoukhlijMatExtract"
BASELINE = "Keyword baseline"
CSV_COLUMNS = ("system", "property", "level", "extracted", "tp", "fp", "fn", "precision", "precision_low",
               "precision_high", "recall", "recall_low", "recall_high", "f1", "f1_low", "f1_high")


HOW_TO_ADD = """## Adding another method

Run it on the same PDFs (the pdf column of the workbook's Papers sheet) and write what it finds to a CSV with the
columns paper_id, property, material, value (unit, component, origin, confidence optional; property one of
activation_energy, ionic_conductivity, electronic_conductivity, diffusion_coefficient). Then:

    mme-eval benchmark --tool ChemDataExtractor=cde.csv --tool "LLM prompt=llm.csv"

- ChemDataExtractor 2: parse each PDF (or its text) with its Document class and keep the records of the properties
  above; write one row per record.
- A large language model: give it each paper's text and the same instructions as the annotation guide, ask for JSON
  rows, and write them out; record the model, its version, the prompt and the date in the paper."""


def parse_tool(text: str) -> Tuple[str, Path]:
    """“NAME=FILE.csv” (or a file alone: its name is the system's)."""
    name, _, path = text.partition("=")
    if not path:
        path, name = name, Path(name).stem
    return name.strip(), Path(path.strip()).expanduser()


def run(gold: Path, out: Path, sources: Optional[Sequence[Path]] = None, tools: Sequence[str] = (),
        with_baseline: bool = True, seed: int = 7) -> Dict[str, object]:
    """Scores every system and writes the benchmark. Returns {"systems": {name: metrics}, "differences": …,
    "paths": {…}, "notes": [...]}. Raises AnnotationError for a workbook that cannot be scored."""
    annotation = read_annotation(Path(gold))
    if not annotation.done:
        raise AnnotationError(f"No paper of {annotation.path} is marked done yet (Papers sheet, column done = yes): "
                              "annotate some papers first.")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    record = Run("benchmark", out, settings={"workbook": str(annotation.path.resolve()), "seed": seed,
                                             "sources": [str(s) for s in sources or []], "tools": list(tools),
                                             "baseline": with_baseline})
    ours: List[Item] = annotation.extracted
    label = "the values of the workbook (the run it was made from)"
    if sources:
        ours = extracted_from_databases(annotation, [Path(s) for s in sources])
        label = "the values now in " + ", ".join(str(s) for s in sources)
    systems: Dict[str, Dict] = {OURS: evaluate(annotation, ours, seed=seed)}
    differences: Dict[str, Dict] = {}
    notes: List[str] = [f"{OURS}: {label}."]
    if with_baseline:
        found = baseline.predict(annotation, Path(gold))
        missing = baseline.missing_pdfs(annotation, Path(gold))
        baseline.to_csv(found, out / "baseline_predictions.csv")
        systems[BASELINE] = evaluate(annotation, found, seed=seed)
        differences[BASELINE] = paired_difference(annotation, ours, found, seed=seed)
        notes.append(baseline.DESCRIPTION)
        if missing:
            notes.append(f"The baseline could not read {len(missing)} of the {len(annotation.done)} papers (their "
                         "PDF is not on this computer): it scores no value for them, which lowers its recall.")
    for text in tools:
        name, path = parse_tool(text)
        theirs = predictions_from_csv(path, annotation)
        systems[name] = evaluate(annotation, theirs, seed=seed)
        differences[name] = paired_difference(annotation, ours, theirs, seed=seed)
        notes.append(f"{name}: {path.name}.")
    paths = {"report": out / "benchmark.md", "table": out / "benchmark.csv", "figure": out / "benchmark.png"}
    rows = table_rows(systems)
    with open(paths["table"], "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    paths["report"].write_text(report(systems, differences, annotation, notes, seed), encoding="utf-8")
    if not figure(systems, paths["figure"]):
        paths.pop("figure")
    record.finish({"papers": len(annotation.done), "reference_values": len(annotation.gold), "systems": list(systems)},
                  files=[p.name for p in paths.values()] + (["baseline_predictions.csv"] if with_baseline else []))
    return {"systems": systems, "differences": differences, "paths": paths, "notes": notes}


def table_rows(systems: Dict[str, Dict]) -> List[Dict[str, object]]:
    rows = []
    for name, metrics in systems.items():
        for level in ("record", "value"):
            for scope, s in metrics["levels"][level].items():
                row = {"system": name, "property": scope, "level": level, "extracted": s["tp"] + s["fp"],
                       "tp": s["tp"], "fp": s["fp"], "fn": s["fn"]}
                for key in ("precision", "recall", "f1"):
                    value, interval = s.get(key), (s.get("ci95") or {}).get(key)
                    row[key] = "" if value is None else f"{value:.4f}"
                    row[f"{key}_low"] = "" if not interval else f"{interval[0]:.4f}"
                    row[f"{key}_high"] = "" if not interval else f"{interval[1]:.4f}"
                rows.append(row)
    return rows


def _pct(x) -> str:
    return "–" if x is None else f"{100 * x:.1f}"


def report(systems: Dict[str, Dict], differences: Dict[str, Dict], annotation, notes: List[str], seed: int) -> str:
    lines = [f"# Benchmark on {len(annotation.done)} annotated papers", "",
             f"{len(annotation.gold)} reference values (correct, partly correct or missed, as a person marked them). "
             f"Software: MoukhlijMatExtract {version() or ''}. Bootstrap seed {seed}.", "",
             "**Systems.**", ""] + [f"- {note}" for note in notes] + ["",
             "**Levels.** *record*: the right value of the right material; *value*: the right value, any material.", ""]
    lines.append(comparison_text(systems, differences))
    lines += ["## By property (record level, F1 in % with 95 % interval)", "",
              "| System | " + " | ".join(p.replace("_", " ") for p in PROPERTIES) + " |",
              "|---|" + "---|" * len(PROPERTIES)]
    for name, metrics in systems.items():
        cells = []
        for prop in PROPERTIES:
            s = metrics["levels"]["record"].get(prop)
            if not s:
                cells.append("–")
                continue
            interval = (s.get("ci95") or {}).get("f1")
            cells.append(_pct(s["f1"]) + (f" [{_pct(interval[0])}–{_pct(interval[1])}]" if interval else ""))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "Every number: benchmark.csv. The figure: benchmark.png.", "", HOW_TO_ADD, ""]
    return "\n".join(lines)


def figure(systems: Dict[str, Dict], path: Path) -> bool:
    """Precision, recall and F1 (record level, all properties) of each system, with their 95 % intervals."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    names = list(systems)
    measures = (("precision", "Precision"), ("recall", "Recall"), ("f1", "F1"))
    colours = ("#2a78d6", "#eb6834", "#1baf7a")  # categorical slots 1–3, in this order (validated, all pairs)
    surface, ink, muted = "#fcfcfb", "#1f1f1e", "#6b6b68"
    fig, axis = plt.subplots(figsize=(1.9 * len(names) + 3, 4.2), dpi=150, facecolor=surface)
    axis.set_facecolor(surface)
    width = 0.26
    for index, (measure, label) in enumerate(measures):
        heights, low, high = [], [], []
        for name in names:
            s = systems[name]["levels"]["record"]["all"]
            value = s.get(measure) or 0.0
            interval = (s.get("ci95") or {}).get(measure) or (value, value)
            heights.append(100 * value)
            low.append(100 * max(0.0, value - interval[0]))
            high.append(100 * max(0.0, interval[1] - value))
        positions = [n + (index - 1) * width for n in range(len(names))]
        bars = axis.bar(positions, heights, width, color=colours[index], edgecolor=surface, linewidth=2, label=label,
                        yerr=[low, high], error_kw={"ecolor": muted, "elinewidth": 1, "capsize": 3})
        if measure == "f1":  # one direct label per system: its F1
            for bar, height, up in zip(bars, heights, high):
                axis.text(bar.get_x() + bar.get_width() / 2, height + up + 1.5, f"{height:.0f}", ha="center",
                          va="bottom", fontsize=8, color=ink)
    axis.set_xticks(range(len(names)))
    axis.set_xticklabels(names, color=ink)
    axis.set_ylabel("%  (record level, 95 % interval)", color=muted)
    axis.set_ylim(0, 105)
    axis.tick_params(colors=muted, length=0)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.spines["bottom"].set_color("#d4d4d0")
    axis.grid(axis="y", color="#ececea", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, ncol=3, loc="upper right", labelcolor=ink)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return True
