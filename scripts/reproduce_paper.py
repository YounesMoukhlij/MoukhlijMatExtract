# scripts/reproduce_paper.py
"""make paper: every table and figure of the article, made again from the data, in one folder.

    python scripts/reproduce_paper.py [--data DIR ...] [--gold FILE] [--tool NAME=CSV ...] [--out DIR]

From the results folders (default: LocalExtraction/local_output and WebScraping/web_output of ~/MoukhlijMatExtract,
whichever exist; or the databases of a release) it writes, into paper/ (or --out):

  tables/database_summary.csv   values, unique measurements, papers and materials of each property
  tables/duplicates.csv         the values counted more than once (repeated in a paper, quoted by another)
  figures/activation_energy.png the activation energies measured (this work, experimental, Arrhenius), by component
  figures/conductivity_rt.png   the room-temperature ionic conductivities measured (log10)
  ranking/                      mme-rank, with fixed settings
  classification/               mme-classify: the classes and the classification by property
  evaluation/scores, benchmark  mme-eval score and benchmark, when the workbook has annotated papers
  environment.json              the commit (and whether the copy was changed), Python, the platform, every package's
                                version, the hash of requirements.lock, the seeds, the inputs' checksums
  RESULTS.md                    what was made, from what, by which command; what was skipped and why

Seeds are fixed (bootstrap 7) and PYTHONHASHSEED=0 for the commands run: the same data and the same environment give the
same files. Each step's output is in logs/<step>.log; a failed step is reported, the others still run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
for _group in ("app", "export", "core"):  # the packages are in core/, export/ and app/
    if str(ROOT / _group) not in sys.path:
        sys.path.insert(0, str(ROOT / _group))

SEED = 7
PROPERTIES = {"activation_energy": ("activation_energy_eV", "eV"),
              "ionic_conductivity": ("ionic_conductivity_S_cm", "S/cm"),
              "electronic_conductivity": ("electronic_conductivity_S_cm", "S/cm"),
              "diffusion_coefficient": ("diffusion_coefficient_cm2_s", "cm2/s")}
# Chart styling: categorical slots 1–3 of the validated palette, a light surface, quiet axes.
COLOURS = ("#2a78d6", "#eb6834", "#1baf7a")
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#1f1f1e", "#6b6b68", "#ececea"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def environment(inputs: Sequence[Path], gold: Optional[Path]) -> Dict:
    from importlib.metadata import distributions
    lock = ROOT / "requirements.lock"
    files = {}
    for folder in inputs:
        for path in sorted(folder.glob("*.csv")):
            files[f"{folder.name}/{path.name}"] = sha256(path)
    if gold and gold.is_file():
        files[gold.name] = sha256(gold)
    return {
        "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": _git("rev-parse", "HEAD") or os.environ.get("MME_COMMIT", ""),  # (the Docker image has no .git)
        "uncommitted_changes": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
        "requirements_lock_sha256": sha256(lock) if lock.is_file() else "",
        "seeds": {"bootstrap": SEED, "PYTHONHASHSEED": 0},
        "packages": {d.metadata["Name"]: d.version for d in sorted(distributions(), key=lambda d: d.metadata["Name"].lower())
                     if d.metadata["Name"]},
        "inputs": files,
    }


def _rows(path: Path) -> List[Dict[str, str]]:
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _write(path: Path, columns: Sequence[str], rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _number(text) -> Optional[float]:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def tables(inputs: Sequence[Path], out: Path) -> Dict[str, List[Dict]]:
    """database_summary.csv and duplicates.csv; returns the values of each property, marked."""
    from LocalExtraction import duplicates
    years = duplicates.years_of(inputs)
    summary, dup_rows, marked_by = [], [], {}
    for prop, (column, unit) in PROPERTIES.items():
        rows = [{**r, "database": folder.name} for folder in inputs for r in _rows(folder / f"{prop}.csv")]
        if not rows:
            continue
        marked = duplicates.mark(rows, prop, years)
        marked_by[prop] = marked
        counts = duplicates.summary(marked)
        own = [r for r in marked if r.get("attribution", "").strip() != "cited"]
        summary.append({"property": prop, "unit": unit, "values": counts["values"],
                        "unique_measurements": counts["unique values"], "papers": len({r["paper_id"] for r in marked}),
                        "materials": len({duplicates.material_of(r) for r in marked}),
                        "this_work": len(own), "cited": len(marked) - len(own),
                        "experimental": sum(r.get("data_origin") == "experimental" for r in marked),
                        "simulation": sum(r.get("data_origin") == "simulation" for r in marked)})
        dup_rows.append({"property": prop, **counts})
    _write(out / "tables" / "database_summary.csv", ["property", "unit", "values", "unique_measurements", "papers",
                                                    "materials", "this_work", "cited", "experimental", "simulation"],
           summary)
    _write(out / "tables" / "duplicates.csv", ["property", "values", "measurements", "unique values", "same paper",
                                              "cited", "possible"], dup_rows)
    return marked_by


def _axes(plt, width=6.4, height=3.8):
    fig, axis = plt.subplots(figsize=(width, height), dpi=200, facecolor=SURFACE)
    axis.set_facecolor(SURFACE)
    axis.tick_params(colors=MUTED, length=0)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.spines["bottom"].set_color("#d4d4d0")
    axis.grid(axis="y", color=GRID, linewidth=0.8)
    axis.set_axisbelow(True)
    return fig, axis


def figures(marked_by: Dict[str, List[Dict]], out: Path) -> List[str]:
    """The figures; returns their names (none when matplotlib is missing or there is no data)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    from LocalExtraction.duplicates import is_duplicate
    made = []
    folder = out / "figures"
    folder.mkdir(parents=True, exist_ok=True)

    def measured(prop):
        return [r for r in marked_by.get(prop, []) if not is_duplicate(r) and r.get("attribution") != "cited"
                and r.get("data_origin") == "experimental"]

    energies = [r for r in measured("activation_energy") if r.get("energy_kind", "arrhenius") == "arrhenius"]
    if energies:
        fig, axis = _axes(plt)
        bins = [i / 20 for i in range(0, 31)]  # 0 to 1.5 eV, 0.05 eV wide
        series = [(c, [v for r in energies if r.get("transport_component") == c
                       for v in [_number(r["activation_energy_eV"])] if v is not None and 0 < v <= 1.5])
                  for c in ("bulk", "grain_boundary", "total")]
        series = [(c, v) for c, v in series if v]
        axis.hist([v for _, v in series], bins=bins, stacked=True, color=COLOURS[:len(series)], edgecolor=SURFACE,
                  linewidth=1, label=[f"{c.replace('_', ' ')} (n = {len(v)})" for c, v in series])
        axis.set_xlabel("Activation energy (eV)", color=MUTED)
        axis.set_ylabel("Measurements", color=MUTED)
        axis.legend(frameon=False, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(folder / "activation_energy.png")
        plt.close(fig)
        made.append("activation_energy.png")

    from MLDataset.export import temperature_K
    conductivities = [v for r in measured("ionic_conductivity") if temperature_K(r.get("temperature", ""))[2]
                      for v in [_number(r["ionic_conductivity_S_cm"])] if v and 1e-12 < v < 1]
    if conductivities:
        fig, axis = _axes(plt)
        logs = [math.log10(v) for v in conductivities]
        axis.hist(logs, bins=[x / 4 for x in range(-48, 1)], color=COLOURS[0], edgecolor=SURFACE, linewidth=1)
        axis.set_xlabel("log10 ionic conductivity at room temperature (S/cm)", color=MUTED)
        axis.set_ylabel("Measurements", color=MUTED)
        axis.set_title(f"n = {len(logs)} measurements (this work, experimental, each counted once)", color=INK,
                       fontsize=9, loc="left")
        fig.tight_layout()
        fig.savefig(folder / "conductivity_rt.png")
        plt.close(fig)
        made.append("conductivity_rt.png")
    return made


def run_step(name: str, args: List[str], logs: Path) -> Dict[str, object]:
    """Runs a command of the program with this Python; its output goes to logs/<name>.log."""
    logs.mkdir(parents=True, exist_ok=True)
    packages = os.pathsep.join(str(ROOT / group) for group in ("core", "export", "app"))  # also without an install
    env = {**os.environ, "PYTHONHASHSEED": "0", "MPLBACKEND": "Agg",
           "PYTHONPATH": os.pathsep.join(p for p in (packages, os.environ.get("PYTHONPATH", "")) if p)}
    started = time.time()
    with open(logs / f"{name}.log", "w", encoding="utf-8") as log:
        log.write("$ python " + " ".join(args) + "\n\n")  # (the log keeps the full paths)
        log.flush()
        code = subprocess.run([sys.executable, *args], stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT).returncode
    shown = " ".join(args).replace(str(Path.home()), "~")
    return {"step": name, "command": "python " + shown, "ok": code == 0, "code": code,
            "seconds": round(time.time() - started, 1)}


def annotated(gold: Optional[Path]) -> bool:
    if not gold or not gold.is_file():
        return False
    try:
        from Evaluation.score import AnnotationError, read_annotation
        return bool(read_annotation(gold).done)
    except Exception:
        return False


def results_text(env: Dict, inputs: Sequence[Path], steps: List[Dict], made_figures: List[str], skipped: List[str],
                 out: Path) -> str:
    lines = ["# Results of the article, made again", "",
             f"Made {env['made_at']} from commit `{env['commit'][:12] or 'unknown'}`"
             + (" **with uncommitted changes**" if env["uncommitted_changes"] else "")
             + f", Python {env['python']} on {env['platform']}.", "",
             "Inputs: " + ", ".join(f"`{p}`" for p in inputs) + ". Their checksums, and every package's version: "
             "`environment.json`.", "", "## Tables", ""]
    summary = _rows(out / "tables" / "database_summary.csv")
    if summary:
        lines += ["| Property | Values | Unique measurements | Papers | Materials | This work | Cited |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        lines += [f"| {r['property'].replace('_', ' ')} | {r['values']} | {r['unique_measurements']} | {r['papers']} | "
                  f"{r['materials']} | {r['this_work']} | {r['cited']} |" for r in summary]
        lines += ["", "`tables/database_summary.csv`, `tables/duplicates.csv` (a value repeated in its paper or quoted "
                  "from another is one measurement).", ""]
    lines += ["## Figures", ""] + ([f"- `figures/{name}`" for name in made_figures] or ["(none)"]) + [""]
    lines += ["## Steps", "", "| Step | Command | Result | Time |", "|---|---|---|---:|"]
    lines += [f"| {s['step']} | `{s['command']}` | {'done' if s['ok'] else 'FAILED (exit ' + str(s['code']) + ')'} | "
              f"{s['seconds']} s |" for s in steps]
    if skipped:
        lines += ["", "## Skipped", ""] + [f"- {why}" for why in skipped]
    lines += ["", "Each step's output: `logs/`.", ""]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    from Evaluation.about import DEFAULT_SHEET, DEFAULT_SOURCES
    from LocalExtraction.about import PROJECT_HOME
    parser = argparse.ArgumentParser(prog="make paper", description="Every table and figure of the article, made "
                                     "again from the data, with the environment recorded.")
    parser.add_argument("--data", nargs="+", type=Path, metavar="DIR",
                        help="Results folders (default: LocalExtraction/local_output and WebScraping/web_output)")
    parser.add_argument("--gold", type=Path, default=DEFAULT_SHEET, metavar="FILE",
                        help="The annotated workbook (default: Evaluation/annotation.xlsx)")
    parser.add_argument("--tool", action="append", default=[], metavar="NAME=CSV",
                        help="Another tool's values for the benchmark (repeat for several)")
    parser.add_argument("--out", type=Path, default=PROJECT_HOME / "paper", metavar="DIR",
                        help="Where to write (default: ~/MoukhlijMatExtract/paper)")
    args = parser.parse_args(argv)
    inputs = [p.expanduser().resolve() for p in (args.data or DEFAULT_SOURCES) if p.expanduser().is_dir()]
    if not inputs:
        print("No results folder: give them with --data (make paper DATA='<folder> ...').", file=sys.stderr)
        return 1
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    gold = args.gold.expanduser().resolve() if args.gold else None
    logs = out / "logs"
    print(f"Making the article's results into {out} …")
    env = environment(inputs, gold)
    (out / "environment.json").write_text(json.dumps(env, indent=2), encoding="utf-8")

    marked = tables(inputs, out)
    made_figures = figures(marked, out)
    print(f"  tables and {len(made_figures)} figures")
    sources = [str(p) for p in inputs]
    steps, skipped = [], []
    plan = [("ranking", ["-m", "SelectingTopMaterial", "--source", *sources, "--out", str(out / "ranking"),
                         "--no-color", "--quiet"]),
            ("classification", ["-m", "Classification", "--source", *sources, "--out", str(out / "classification"),
                                "--force"])]
    if annotated(gold):
        plan.append(("evaluation-score", ["-m", "Evaluation", "score", "--gold", str(gold), "--out",
                                          str(out / "evaluation" / "scores"), "--seed", str(SEED)]))
        bench = ["-m", "Evaluation", "benchmark", "--gold", str(gold), "--out", str(out / "evaluation" / "benchmark"),
                 "--seed", str(SEED)]
        for tool in args.tool:
            bench += ["--tool", tool]
        plan.append(("evaluation-benchmark", bench))
    else:
        skipped.append(f"Evaluation (scores, benchmark): {gold} has no paper marked done yet — annotate it "
                       "(mme-eval sheet, then the workbook), and run make paper again.")
    for name, command in plan:
        print(f"  {name} …", flush=True)
        steps.append(run_step(name, command, logs))
        if not steps[-1]["ok"]:
            print(f"    failed: see {logs / (name + '.log')}")
    (out / "RESULTS.md").write_text(results_text(env, inputs, steps, made_figures, skipped, out), encoding="utf-8")
    print(f"Done: {out / 'RESULTS.md'}")
    return 0 if all(s["ok"] for s in steps) else 1


if __name__ == "__main__":
    sys.exit(main())
