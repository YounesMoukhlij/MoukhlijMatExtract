# Evaluation/score.py
"""Scores the extraction against the annotated workbook.

The reference ("gold") values of a paper marked done are: its Values rows marked correct, its Values
rows marked partly with the annotator's corrections, and its Missed rows. The extracted values are the
Values rows as they were when the workbook was made — or, with `sources`, the values a newer run of
the program wrote, so a new version is measured against the same reference.

Two levels, for each property and overall:
  value   — the right number for the right property in the right paper;
  record  — the same, for the right material too.
Each with precision, recall, F1 and a 95 % interval from resampling the papers (bootstrap). Also the
accuracy of the component and origin of the values found, how well the confidence column predicts
correctness (calibration), and the kinds of errors the annotators named."""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from .about import PROPERTIES, VERDICTS
from .compare import max_matching, same_material, same_value, to_database_unit
from .sheet import read_database

BOOTSTRAP = 2000
CONFIDENCE_BINS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0000001)


class AnnotationError(ValueError):
    """The workbook cannot be scored as it is (the message says where)."""


@dataclass
class Item:
    paper: str
    prop: str
    material: str
    value: float
    component: str = ""
    origin: str = ""
    confidence: Optional[float] = None
    row_id: str = ""
    title: str = ""
    sentence: str = ""
    extracted_from: str = ""
    error_type: str = ""
    kind: str = ""  # gold: "correct", "partly" or "missed"


@dataclass
class Annotation:
    path: Path
    done: List[str]                     # the paper_ids scored
    gold: List[Item]
    extracted: List[Item]               # the Values rows (the snapshot), with their verdicts
    verdicts: Dict[str, str]            # row_id -> verdict, papers done only
    error_types: Counter
    sources: Dict[str, str]             # paper_id -> results folder name
    titles: Dict[str, str]
    warnings: List[str] = field(default_factory=list)


def _text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    return "" if text.upper() in ("NONE", "NAN") else text


def _float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def read_annotation(path: Path) -> Annotation:
    """The annotated workbook, checked: what cannot be scored raises AnnotationError, what is doubtful
    is listed in .warnings."""
    path = Path(path)
    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str, keep_default_na=False)
    except FileNotFoundError:
        raise AnnotationError(f"There is no workbook {path} (make one with: mme-eval sheet)")
    except Exception as error:
        raise AnnotationError(f"{path} cannot be read as a workbook: {error}")
    for name in ("Papers", "Values", "Missed"):
        if name not in sheets:
            raise AnnotationError(f"{path} has no {name} sheet — is it a workbook made by mme-eval sheet?")
    papers, values, missed = sheets["Papers"], sheets["Values"], sheets["Missed"]
    warnings: List[str] = []

    done = [_text(r["paper_id"]) for _, r in papers.iterrows() if _text(r.get("done", "")).lower() in ("yes", "y", "done")]
    done_set = set(done)
    sources = {_text(r["paper_id"]): _text(r.get("source", "")) for _, r in papers.iterrows()}
    titles = {_text(r["paper_id"]): _text(r.get("title", "")) for _, r in papers.iterrows()}

    gold: List[Item] = []
    extracted: List[Item] = []
    verdicts: Dict[str, str] = {}
    error_types: Counter = Counter()
    unfinished = set()
    for n, row in values.iterrows():
        paper = _text(row["paper_id"])
        prop = _text(row["property"])
        if prop not in PROPERTIES:
            raise AnnotationError(f"Values sheet, row {n + 2}: unknown property “{prop}”")
        value = _float(row["value"])
        item = Item(paper, prop, _text(row["material"]), value, _text(row.get("component")), _text(row.get("origin")),
                    _float(row.get("confidence")), _text(row.get("row_id")), _text(row.get("title")),
                    _text(row.get("sentence")), _text(row.get("extracted_from")), _text(row.get("error_type")))
        if paper not in done_set:
            continue
        extracted.append(item)
        verdict = _text(row.get("verdict")).lower()
        if verdict not in VERDICTS:
            unfinished.add(paper)
            if verdict:
                raise AnnotationError(f"Values sheet, row {n + 2} ({item.row_id}): verdict “{verdict}” — use "
                                      + ", ".join(VERDICTS))
            continue
        verdicts[item.row_id] = verdict
        if item.error_type:
            error_types[item.error_type] += 1
        if verdict == "wrong":
            if not item.error_type:
                warnings.append(f"{item.row_id}: wrong, without an error_type")
            continue
        truth = Item(paper, prop, item.material, value, item.component, item.origin, row_id=item.row_id,
                     title=item.title, sentence=item.sentence, extracted_from=item.extracted_from, kind=verdict)
        if verdict == "partly":
            changed = False
            if _text(row.get("true_material")):
                truth.material, changed = _text(row["true_material"]), True
            if _text(row.get("true_value")):
                number, why = to_database_unit(prop, row["true_value"], _text(row.get("true_unit")))
                if number is None:
                    raise AnnotationError(f"Values sheet, row {n + 2} ({item.row_id}): true_value — {why}")
                truth.value, changed = number, True
            for name in ("component", "origin"):
                if _text(row.get(f"true_{name}")):
                    setattr(truth, name, _text(row[f"true_{name}"]))
                    changed = True
            if not changed:
                warnings.append(f"{item.row_id}: partly, but no true_ column says what is wrong (scored as correct)")
        gold.append(truth)
    for paper in sorted(unfinished):
        warnings.append(f"{paper}: marked done but some of its values have no verdict — the paper is left out")
    if unfinished:
        done = [p for p in done if p not in unfinished]
        done_set = set(done)
        gold = [g for g in gold if g.paper in done_set]
        extracted = [e for e in extracted if e.paper in done_set]
        verdicts = {e.row_id: verdicts[e.row_id] for e in extracted if e.row_id in verdicts}

    for n, row in missed.iterrows():
        paper, prop = _text(row.get("paper_id")), _text(row.get("property"))
        if not any(_text(row.get(c)) for c in ("paper_id", "property", "material", "value")):
            continue  # a blank row
        where = f"Missed sheet, row {n + 2}"
        if not paper or not prop or not _text(row.get("value")):
            raise AnnotationError(f"{where}: paper_id, property and value are needed")
        if prop not in PROPERTIES:
            raise AnnotationError(f"{where}: unknown property “{prop}”")
        if paper not in sources:
            raise AnnotationError(f"{where}: “{paper}” is not a paper of the Papers sheet")
        if paper not in done_set:
            continue
        number, why = to_database_unit(prop, row["value"], _text(row.get("unit")))
        if number is None:
            raise AnnotationError(f"{where}: {why}")
        if not _text(row.get("material")):
            warnings.append(f"{where}: no material (it can match only at the value level)")
        gold.append(Item(paper, prop, _text(row.get("material")), number, _text(row.get("component")),
                         _text(row.get("origin")), title=titles.get(paper, ""), sentence=_text(row.get("sentence")),
                         kind="missed"))
    return Annotation(path, done, gold, extracted, verdicts, error_types, sources, titles, warnings)


def extracted_from_databases(annotation: Annotation, folders: Sequence[Path]) -> List[Item]:
    """The values a (newer) run wrote for the papers of the annotation, read from the results folders."""
    wanted = set(annotation.done)
    items: List[Item] = []
    for folder in folders:
        database = read_database(Path(folder))
        for _, row in database.values.iterrows():
            paper = row["paper_id"]
            if paper not in wanted or annotation.sources.get(paper, database.folder.name) != database.folder.name:
                continue
            items.append(Item(paper, row["property"], _text(row["material"]), _float(row["value"]),
                              _text(row["component"]), _text(row["origin"]), _float(row["confidence"]),
                              title=_text(row["title"]), sentence=_text(row["sentence"]),
                              extracted_from=_text(row["extracted_from"])))
    return items


PREDICTION_COLUMNS = ("paper_id", "property", "material", "value")  # needed; unit, component, origin, confidence: optional


def predictions_from_csv(path: Path, annotation: Annotation) -> List[Item]:
    """Another tool's values for the papers of the annotation, from a CSV file with the columns paper_id
    (the PDF file name, as in the workbook), property (activation_energy, ionic_conductivity,
    electronic_conductivity, diffusion_coefficient), material, value and — optional — unit (as written:
    meV, mS/cm, …; empty = the database unit), component, origin, confidence."""
    try:
        table = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (OSError, ValueError) as error:
        raise AnnotationError(f"{path} cannot be read as a CSV file: {error}")
    missing = [c for c in PREDICTION_COLUMNS if c not in table.columns]
    if missing:
        raise AnnotationError(f"{path} has no column {', '.join(missing)} (needed: {', '.join(PREDICTION_COLUMNS)})")
    done = set(annotation.done)
    items: List[Item] = []
    for n, row in table.iterrows():
        paper, prop = _text(row["paper_id"]), _text(row["property"]).lower().replace(" ", "_")
        if paper not in done:
            continue
        if prop not in PROPERTIES:
            raise AnnotationError(f"{path}, row {n + 2}: unknown property “{row['property']}”")
        number, why = to_database_unit(prop, row["value"], _text(row.get("unit", "")))
        if number is None:
            raise AnnotationError(f"{path}, row {n + 2}: {why}")
        items.append(Item(paper, prop, _text(row["material"]), number, _text(row.get("component", "")),
                          _text(row.get("origin", "")), _float(row.get("confidence")),
                          title=annotation.titles.get(paper, ""), sentence=_text(row.get("sentence", ""))))
    return items


def paired_difference(annotation: Annotation, first: List[Item], second: List[Item], level: str = "record",
                      seed: int = 7, rounds: int = BOOTSTRAP) -> Dict[str, Optional[float]]:
    """F1(first) − F1(second) on the same papers, with its 95 % interval and the share of resamplings where
    the second is at least as good (a one-sided p-value): the papers are resampled together for both."""
    props = list(PROPERTIES)
    a = _counts(match(first, annotation.gold), annotation.done, props)
    b = _counts(match(second, annotation.gold), annotation.done, props)
    papers = sorted(a)

    def f1(rows, picks):
        tp = sum(rows[p][level][0] for p in picks)
        fp = sum(rows[p][level][1] for p in picks)
        fn = sum(rows[p][level][2] for p in picks)
        return _prf(tp, fp, fn)["f1"] or 0.0

    observed = f1(a, papers) - f1(b, papers)
    if len(papers) < 2:
        return {"difference": observed, "ci95": None, "p_value": None}
    rng = random.Random(seed)
    diffs = []
    for _ in range(rounds):
        picks = [papers[rng.randrange(len(papers))] for _ in papers]
        diffs.append(f1(a, picks) - f1(b, picks))
    diffs.sort()
    return {"difference": observed, "ci95": (diffs[int(0.025 * (rounds - 1))], diffs[int(0.975 * (rounds - 1))]),
            "p_value": sum(d <= 0 for d in diffs) / rounds}


def comparison_text(systems: Dict[str, Dict], differences: Dict[str, Dict]) -> str:
    """The systems side by side (all properties), and how MoukhlijMatExtract differs from each."""
    lines = ["# Systems compared on the same annotated papers", "",
             "Precision, recall and F1 in %, all properties, with 95 % bootstrap intervals over papers.", "",
             "| System | Level | Extracted | Precision | Recall | F1 |", "|---|---|---:|---|---|---|"]
    for name, metrics in systems.items():
        for level in ("record", "value"):
            s = metrics["levels"][level].get("all")
            if s:
                lines.append(f"| {name} | {level} | {s['tp'] + s['fp']} | {_pct(s['precision'])}{_ci(s['ci95']['precision'])} | "
                             f"{_pct(s['recall'])}{_ci(s['ci95']['recall'])} | {_pct(s['f1'])}{_ci(s['ci95']['f1'])} |")
    if differences:
        lines += ["", "## MoukhlijMatExtract minus each other system (record-level F1, paired bootstrap)", "",
                  "| Other system | Difference (points) | 95 % interval | p (other at least as good) |", "|---|---:|---|---:|"]
        for name, d in differences.items():
            ci = "–" if not d["ci95"] else f"{100 * d['ci95'][0]:+.1f} to {100 * d['ci95'][1]:+.1f}"
            p = "–" if d["p_value"] is None else f"{d['p_value']:.3f}"
            lines.append(f"| {name} | {100 * d['difference']:+.1f} | {ci} | {p} |")
    lines.append("")
    return "\n".join(lines)


# ---- matching and counting ---------------------------------------------------------------------------

@dataclass
class Match:
    record: List[Tuple[Item, Item]]          # (extracted, gold): right value and material
    value_only: List[Tuple[Item, Item]]      # right value (any material)
    false_positives: List[Item]              # record level
    false_negatives: List[Item]              # record level


def _agreeing(e: Item, g: Item) -> float:
    """How well two values that match agree besides: the same row of the workbook, then the same
    component and origin, then the closer number."""
    closeness = 1.0 / (1.0 + abs((e.value or 0) - (g.value or 0)) / max(abs(g.value or 0), 1e-300))
    return (4.0 * bool(e.row_id and e.row_id == g.row_id) + 2.0 * (e.component == g.component)
            + 1.0 * (e.origin == g.origin) + 0.5 * closeness)


def match(extracted: Sequence[Item], gold: Sequence[Item]) -> Dict[Tuple[str, str], Match]:
    """For each (paper, property): the largest matching at each level."""
    groups = defaultdict(lambda: ([], []))
    for item in extracted:
        groups[(item.paper, item.prop)][0].append(item)
    for item in gold:
        groups[(item.paper, item.prop)][1].append(item)
    results = {}
    for key, (ex, gd) in groups.items():
        prop = key[1]
        record_pairs = max_matching(ex, gd, lambda e, g: same_value(prop, e.value, g.value)
                                    and bool(g.material) and same_material(e.material, g.material), _agreeing)
        value_pairs = max_matching(ex, gd, lambda e, g: same_value(prop, e.value, g.value), _agreeing)
        matched_ex = {i for i, _ in record_pairs}
        matched_gd = {j for _, j in record_pairs}
        results[key] = Match([(ex[i], gd[j]) for i, j in record_pairs], [(ex[i], gd[j]) for i, j in value_pairs],
                             [e for i, e in enumerate(ex) if i not in matched_ex],
                             [g for j, g in enumerate(gd) if j not in matched_gd])
    return results


def _prf(tp: int, fp: int, fn: int) -> Dict[str, Optional[float]]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * tp / (2 * tp + fp + fn)) if tp + fp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _counts(matches: Dict[Tuple[str, str], Match], papers: Sequence[str], props: Sequence[str]) -> Dict[str, Dict[str, Tuple[int, int, int]]]:
    """paper -> level -> (tp, fp, fn), for the properties given."""
    table = {p: {"value": [0, 0, 0], "record": [0, 0, 0]} for p in papers}
    for (paper, prop), m in matches.items():
        if prop not in props or paper not in table:
            continue
        n_ex = len(m.record) + len(m.false_positives)
        n_gd = len(m.record) + len(m.false_negatives)
        for level, tp in (("record", len(m.record)), ("value", len(m.value_only))):
            row = table[paper][level]
            row[0] += tp
            row[1] += n_ex - tp
            row[2] += n_gd - tp
    return {p: {lvl: tuple(v) for lvl, v in levels.items()} for p, levels in table.items()}


def _interval(per_paper: Dict[str, Dict[str, Tuple[int, int, int]]], level: str, seed: int,
              rounds: int = BOOTSTRAP) -> Dict[str, Optional[Tuple[float, float]]]:
    """95 % percentile intervals of precision, recall and F1, resampling the papers."""
    papers = sorted(per_paper)
    if len(papers) < 2:
        return {"precision": None, "recall": None, "f1": None}
    rng = random.Random(seed)
    samples = {"precision": [], "recall": [], "f1": []}
    rows = [per_paper[p][level] for p in papers]
    for _ in range(rounds):
        tp = fp = fn = 0
        for _ in papers:
            a, b, c = rows[rng.randrange(len(rows))]
            tp, fp, fn = tp + a, fp + b, fn + c
        scores = _prf(tp, fp, fn)
        for name in samples:
            if scores[name] is not None:
                samples[name].append(scores[name])
    result = {}
    for name, values in samples.items():
        if len(values) < rounds * 0.5:
            result[name] = None
            continue
        values.sort()
        result[name] = (values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))])
    return result


def _calibration(extracted: Sequence[Item], correct_rows: set) -> Dict:
    """Does the confidence say how often a value is right? Bins, expected calibration error, Brier score."""
    scored = [(e.confidence, id(e) in correct_rows) for e in extracted if e.confidence is not None]
    bins = []
    for low, high in zip(CONFIDENCE_BINS, CONFIDENCE_BINS[1:]):
        inside = [(c, ok) for c, ok in scored if low <= c < high]
        if inside:
            bins.append({"from": low, "to": min(high, 1.0), "n": len(inside),
                         "mean_confidence": sum(c for c, _ in inside) / len(inside),
                         "precision": sum(ok for _, ok in inside) / len(inside)})
    n = len(scored)
    ece = sum(b["n"] / n * abs(b["precision"] - b["mean_confidence"]) for b in bins) if n else None
    brier = sum((c - ok) ** 2 for c, ok in scored) / n if n else None
    return {"n": n, "bins": bins, "ece": ece, "brier": brier}


def evaluate(annotation: Annotation, extracted: Optional[List[Item]] = None, seed: int = 7) -> Dict:
    """Every number of the report, as a dict (written to metrics.json)."""
    extracted = annotation.extracted if extracted is None else extracted
    matches = match(extracted, annotation.gold)
    props = [p for p in PROPERTIES if any(i.prop == p for i in (*extracted, *annotation.gold))]
    result = {"papers": len(annotation.done), "gold": len(annotation.gold), "extracted": len(extracted),
              "gold_by_kind": dict(Counter(g.kind for g in annotation.gold)), "levels": {}, "fields": {}}
    for level in ("value", "record"):
        result["levels"][level] = {}
        for scope, scope_props in [("all", props)] + [(p, [p]) for p in props]:
            per_paper = _counts(matches, annotation.done, scope_props)
            totals = [sum(v[level][k] for v in per_paper.values()) for k in range(3)]
            scores = _prf(*totals)
            scores["ci95"] = _interval(per_paper, level, seed)
            result["levels"][level][scope] = scores

    # Fields of the values found (record level): is the component, the origin right?
    for name in ("component", "origin"):
        pairs = [(e, g) for m in matches.values() for e, g in m.record if getattr(g, name)]
        right = sum(getattr(e, name) == getattr(g, name) for e, g in pairs)
        result["fields"][name] = {"n": len(pairs), "accuracy": right / len(pairs) if pairs else None}

    correct = {id(e) for m in matches.values() for e, _ in m.record}
    result["calibration"] = _calibration(extracted, correct)

    by_where = defaultdict(lambda: [0, 0])
    for e in extracted:
        where = e.extracted_from or "unknown"
        by_where[where][0] += 1
        by_where[where][1] += id(e) in correct
    result["precision_by_location"] = {k: {"n": n, "precision": ok / n} for k, (n, ok) in sorted(by_where.items())}
    result["error_types"] = dict(annotation.error_types.most_common())
    result["verdicts"] = dict(Counter(annotation.verdicts.values()))
    result["_matches"] = matches
    return result


# ---- agreement between two annotators -----------------------------------------------------------------

def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> Optional[float]:
    n = len(first)
    if n == 0:
        return None
    observed = sum(a == b for a, b in zip(first, second)) / n
    labels = set(first) | set(second)
    expected = sum((list(first).count(l) / n) * (list(second).count(l) / n) for l in labels)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def agreement(first: Annotation, second: Annotation) -> Dict:
    """On the papers both marked done: Cohen's κ of the verdicts, and the F1 of one reference set
    against the other (value and record level)."""
    shared = [p for p in first.done if p in set(second.done)]
    rows = sorted(set(first.verdicts) & set(second.verdicts))
    rows = [r for r in rows if next((e.paper for e in first.extracted if e.row_id == r), None) in set(shared)]
    a = [first.verdicts[r] for r in rows]
    b = [second.verdicts[r] for r in rows]
    keep = set(shared)
    gold_a = [g for g in first.gold if g.paper in keep]
    gold_b = [g for g in second.gold if g.paper in keep]
    matches = match(gold_a, gold_b)
    per_paper = _counts(matches, shared, list(PROPERTIES))
    result = {"papers": len(shared), "rows": len(rows), "kappa": cohen_kappa(a, b),
              "raw_agreement": (sum(x == y for x, y in zip(a, b)) / len(rows)) if rows else None,
              "confusion": dict(Counter(f"{x} / {y}" for x, y in zip(a, b)))}
    for level in ("value", "record"):
        totals = [sum(v[level][k] for v in per_paper.values()) for k in range(3)]
        result[f"{level}_f1"] = _prf(*totals)["f1"]
    return result


# ---- the report -----------------------------------------------------------------------------------------

def _pct(x: Optional[float]) -> str:
    return "–" if x is None else f"{100 * x:.1f}"


def _ci(pair) -> str:
    return "" if not pair else f" [{100 * pair[0]:.1f}–{100 * pair[1]:.1f}]"


def report_text(metrics: Dict, annotation: Annotation, extracted_label: str, about: Dict[str, str]) -> str:
    lines = ["# MoukhlijMatExtract — extraction accuracy", ""]
    lines += [f"- **Workbook:** {annotation.path}", f"- **Extracted values:** {extracted_label}",
              *[f"- **{k}:** {v}" for k, v in about.items()],
              f"- **Papers scored:** {metrics['papers']} (marked done)",
              f"- **Reference values:** {metrics['gold']} "
              f"({', '.join(f'{v} {k}' for k, v in metrics['gold_by_kind'].items()) or 'none'})",
              f"- **Extracted values in these papers:** {metrics['extracted']}", ""]
    lines += ["Precision, recall and F1 in %, with 95 % bootstrap intervals over papers.",
              "*Value*: right number, property and paper. *Record*: and the right material.", ""]
    for level in ("record", "value"):
        lines += [f"## {level.capitalize()} level", "",
                  "| Property | Extracted | Reference | Precision | Recall | F1 |", "|---|---:|---:|---|---|---|"]
        for scope, s in metrics["levels"][level].items():
            name = "**All**" if scope == "all" else scope.replace("_", " ")
            lines.append(f"| {name} | {s['tp'] + s['fp']} | {s['tp'] + s['fn']} | {_pct(s['precision'])}"
                         f"{_ci(s['ci95']['precision'])} | {_pct(s['recall'])}{_ci(s['ci95']['recall'])} | "
                         f"{_pct(s['f1'])}{_ci(s['ci95']['f1'])} |")
        lines.append("")
    lines += ["## Fields of the values found (record level)", "", "| Field | Compared | Accuracy |", "|---|---:|---:|"]
    for name, f in metrics["fields"].items():
        lines.append(f"| {name} | {f['n']} | {_pct(f['accuracy'])} |")
    cal = metrics["calibration"]
    brier = "–" if cal["brier"] is None else f"{cal['brier']:.3f}"
    lines += ["", "## Calibration of the confidence column", "",
              f"Expected calibration error: {_pct(cal['ece'])} %; Brier score: {brier} ({cal['n']} values).", "",
              "| Confidence | Values | Mean confidence | Share right |", "|---|---:|---:|---:|"]
    for b in cal["bins"]:
        lines.append(f"| {b['from']:.1f}–{b['to']:.1f} | {b['n']} | {b['mean_confidence']:.2f} | {_pct(b['precision'])} |")
    lines += ["", "## Precision by where the value was read", "", "| Read from | Values | Precision |", "|---|---:|---:|"]
    for where, p in metrics["precision_by_location"].items():
        lines.append(f"| {where} | {p['n']} | {_pct(p['precision'])} |")
    lines += ["", "## Errors named by the annotators", "", "| Error | Values |", "|---|---:|"]
    for name, n in metrics["error_types"].items() or [("none named", 0)]:
        lines.append(f"| {name} | {n} |")
    if annotation.warnings:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in annotation.warnings]
    lines += ["", "Every false positive and false negative, with its sentence: errors.csv. Every number: metrics.json.", ""]
    return "\n".join(lines)


def errors_table(metrics: Dict, titles: Dict[str, str]) -> pd.DataFrame:
    rows = []
    for (paper, prop), m in sorted(metrics["_matches"].items()):
        value_found = {id(g) for _, g in m.value_only}
        for e in m.false_positives:
            rows.append({"paper_id": paper, "title": titles.get(paper, e.title), "property": prop, "error": "false positive",
                         "material": e.material, "value": e.value, "component": e.component, "origin": e.origin,
                         "confidence": e.confidence, "row_id": e.row_id, "error_type": e.error_type,
                         "read_from": e.extracted_from, "sentence": e.sentence})
        for g in m.false_negatives:
            rows.append({"paper_id": paper, "title": titles.get(paper, g.title), "property": prop,
                         "error": "missed" if g.kind == "missed" else
                                  ("wrong material" if id(g) in value_found else "false negative"),
                         "material": g.material, "value": g.value, "component": g.component, "origin": g.origin,
                         "confidence": "", "row_id": g.row_id, "error_type": "", "read_from": g.extracted_from,
                         "sentence": g.sentence})
    return pd.DataFrame(rows, columns=["paper_id", "title", "property", "error", "material", "value", "component",
                                       "origin", "confidence", "row_id", "error_type", "read_from", "sentence"])


def write_report(out: Path, metrics: Dict, annotation: Annotation, extracted_label: str,
                 about: Dict[str, str]) -> Dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = {"report": out / "report.md", "metrics": out / "metrics.json", "errors": out / "errors.csv"}
    paths["report"].write_text(report_text(metrics, annotation, extracted_label, about), encoding="utf-8")
    public = {k: v for k, v in metrics.items() if not k.startswith("_")}
    public["made"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    public["workbook"] = str(annotation.path)
    public["extracted_values"] = extracted_label
    public.update(about)
    paths["metrics"].write_text(json.dumps(public, indent=2, ensure_ascii=False), encoding="utf-8")
    errors_table(metrics, annotation.titles).to_csv(paths["errors"], index=False, encoding="utf-8-sig")
    return paths
