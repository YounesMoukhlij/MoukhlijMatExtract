# Evaluation/cli.py
"""mme-eval (python -m Evaluation): how accurate is the extraction?

    mme-eval sheet     a random sample of papers and their extracted values, in a workbook to annotate
    mme-eval score     precision, recall, F1 (95 % intervals), calibration and errors, from the annotations
    mme-eval agree     agreement of two annotators on the same papers (Cohen's kappa, F1)
    mme-eval reference recall against curated databases (OBELiX, Liverpool), on their own papers

Folders and files are relative to ~/MoukhlijMatExtract, like every part."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from LocalExtraction.about import PROJECT_HOME, command_name, enter_project_home, version, version_text
from LocalExtraction.provenance import Run

from .about import DEFAULT_SCORES, DEFAULT_SHEET, DEFAULT_SOURCES, NAME

EPILOG = ("Typical use: mme-eval sheet → annotate Evaluation/annotation.xlsx (its Guide sheet says how) → "
          "mme-eval score. After changing the program and extracting again: mme-eval score --source "
          "LocalExtraction/local_output WebScraping/web_output, to measure the new version against the same "
          "reference. MoukhlijMatExtract (MME) — Created by Younes Moukhlij.")


def _positive(text: str) -> int:
    number = int(text)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def build_parser() -> argparse.ArgumentParser:
    prog = command_name("mme-eval", NAME)
    parser = argparse.ArgumentParser(prog=prog, description="Measures how accurately MoukhlijMatExtract extracts "
                                     "activation energies, conductivities and diffusion coefficients, against "
                                     "values checked by a person.", epilog=EPILOG)
    parser.add_argument("--version", action="version", version=version_text("mme-eval"))
    commands = parser.add_subparsers(dest="command", metavar="{sheet,score,agree,reference}", required=True)

    sheet = commands.add_parser("sheet", help="Draw papers at random and write the workbook to annotate",
                                description="Draws papers at random from the databases — with and without "
                                "extracted values, so recall is measured honestly — and writes a workbook with every "
                                "value extracted from them, to mark correct / partly / wrong, and a sheet for the "
                                "values missed. The same databases and seed give the same papers.", epilog=EPILOG)
    sheet.add_argument("--source", "-s", nargs="+", action="extend", metavar="DIR",
                       help="Results folder(s) to draw from, the most trusted first (default: "
                            "LocalExtraction/local_output and WebScraping/web_output, whichever exist)")
    sheet.add_argument("--papers", "-n", type=_positive, default=60, metavar="N",
                       help="How many papers to draw (default: 60; 50–100 is usual for a publication)")
    sheet.add_argument("--seed", type=int, default=7, help="Seed of the random draw (default: 7)")
    sheet.add_argument("--out", "-o", type=Path, default=DEFAULT_SHEET, metavar="FILE",
                       help="Workbook to write (default: Evaluation/annotation.xlsx)")
    sheet.add_argument("--force", action="store_true",
                       help="Replace an existing workbook; the old one is kept as <name>.<date>.xlsx")
    sheet.add_argument("--all-papers", action="store_true",
                       help="Draw from every paper. By default only the papers mme-release would publish are drawn "
                            "(a legal copy recorded, or the authors' own PDFs), so the scores describe the dataset "
                            "you deposit")

    score = commands.add_parser("score", help="Score the extraction against the annotated workbook",
                                description="Precision, recall and F1 per property and overall, at the value "
                                "level (right number) and the record level (right number and material), with 95 % "
                                "bootstrap intervals; the accuracy of the component and origin; the calibration of "
                                "the confidence column; the errors. Only the papers marked done are scored.",
                                epilog=EPILOG)
    score.add_argument("--gold", "-g", type=Path, default=DEFAULT_SHEET, metavar="FILE",
                       help="The annotated workbook (default: Evaluation/annotation.xlsx)")
    score.add_argument("--source", "-s", nargs="+", action="extend", metavar="DIR",
                       help="Score the values now in these results folders (a newer run) instead of those the "
                            "workbook was made from")
    score.add_argument("--out", "-o", type=Path, default=DEFAULT_SCORES, metavar="DIR",
                       help="Folder of the report (default: Evaluation/scores)")
    score.add_argument("--seed", type=int, default=7, help="Seed of the bootstrap (default: 7)")
    score.add_argument("--predictions", "-p", nargs="+", action="extend", type=Path, metavar="CSV",
                       help="Other tools' values for the same papers (ChemDataExtractor, an LLM, …), each a CSV with "
                            "paper_id, property, material, value [, unit, component, origin, confidence]: scored the "
                            "same way and compared with MoukhlijMatExtract (comparison.md, paired bootstrap)")

    agree = commands.add_parser("agree", help="Agreement of two annotators who annotated copies of one workbook",
                                description="On the papers both marked done: Cohen's kappa of the verdicts, the raw "
                                "agreement, and the F1 of one reference set against the other.", epilog=EPILOG)
    agree.add_argument("first", type=Path, help="The workbook of the first annotator")
    agree.add_argument("second", type=Path, help="The workbook of the second annotator")

    from .reference import DATABASES
    reference = commands.add_parser(
        "reference", help="Recall against curated databases (OBELiX, Liverpool), on their own papers",
        description="Downloads curated databases of solid electrolytes, fetches the legal open copies of their papers "
                    "into Evaluation/reference/papers/ (apart from your databases), extracts them into "
                    "Evaluation/reference/output/, and finds each curated entry among the extracted ionic "
                    "conductivities: same composition, same value (0.1 decade; 2 %), compatible temperature. Each "
                    "step is skipped when already done; PDFs you add by hand to the papers folder are read too.",
        epilog=EPILOG)
    reference.add_argument("--db", nargs="+", choices=sorted(DATABASES), default=sorted(DATABASES),
                           help="Which databases (default: all)")
    reference.add_argument("--no-fetch", action="store_true", help="Do not look for more papers; compare what is there")
    reference.add_argument("--limit", type=_positive, metavar="N", help="Look for at most N more papers in this run")
    reference.add_argument("--refresh", action="store_true", help="Download the curated databases again")
    reference.add_argument("--workers", "-w", type=_positive, default=4, help="PDFs extracted in parallel (default: 4)")
    reference.add_argument("--predictions", nargs="+", action="extend", type=Path, metavar="CSV", default=[],
                           help="Other tools' values for the same PDFs (Evaluation/reference/papers/), scored the same "
                                "way, side by side in the report (columns paper_id, property, material, value, unit)")

    return parser


def _keep_old(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
    shutil.move(str(path), kept)
    return kept


def run_sheet(args) -> int:
    from .sheet import make
    sources = [Path(s).expanduser() for s in args.source] if args.source else list(DEFAULT_SOURCES)
    present = [s for s in sources if (s / "papers.csv").exists()]
    if not present:
        print("There is no database to draw from: extract papers first (mme-local or mme-web).\nLooked in: "
              + ", ".join(str(s) for s in sources), file=sys.stderr)
        return 1
    out = args.out.expanduser()
    if out.exists():
        if not args.force:
            print(f"{out} is already there — it may hold annotations, so it is not replaced.\n"
                  f"Score it (mme-eval score), write elsewhere (--out), or replace it (--force: the old one is kept).",
                  file=sys.stderr)
            return 1
        print(f"The old workbook is kept as {_keep_old(out)}")
    log = None if args.all_papers else PROJECT_HOME / "WebScraping" / "papers" / "scrape_log.csv"
    counts = make(present, out, args.papers, args.seed, version(), legal_only=not args.all_papers, log=log)
    print(f"Wrote {out}\n  {counts['papers']} papers drawn (seed {args.seed}), {counts['without_values']} of them "
          f"without any extracted value; {counts['values']} extracted values to check.\n"
          f"  Next: open it, read its Guide sheet, annotate, then: {command_name('mme-eval', NAME)} score")
    if counts.get("left_out"):
        print(f"  {counts['left_out']} paper(s) with no record of a legal copy were not drawn (--all-papers draws them).")
    if counts["papers"] < args.papers:
        print(f"  (only {counts['papers']} papers to draw from)")
    return 0


def run_score(args) -> int:
    from .score import AnnotationError, evaluate, extracted_from_databases, read_annotation, write_report
    try:
        annotation = read_annotation(args.gold.expanduser())
    except AnnotationError as error:
        print(error, file=sys.stderr)
        return 1
    if not annotation.done:
        print(f"No paper of {annotation.path} is marked done yet (Papers sheet, column done = yes).", file=sys.stderr)
        return 1
    extracted, label = None, "the values in the workbook (the run it was made from)"
    if args.source:
        folders = [Path(s).expanduser() for s in args.source]
        missing = [str(f) for f in folders if not (f / "papers.csv").exists()]
        if missing:
            print("Not a results folder: " + ", ".join(missing), file=sys.stderr)
            return 1
        extracted = extracted_from_databases(annotation, folders)
        label = "now in " + ", ".join(str(f) for f in folders)
    run = Run("evaluation", args.out.expanduser(), settings={"workbook": str(annotation.path.resolve()),
                                                              "scored": label, "bootstrap_seed": args.seed})
    metrics = evaluate(annotation, extracted, seed=args.seed)
    about = {"software": f"MoukhlijMatExtract {version()}".strip(), "bootstrap seed": str(args.seed)}
    paths = write_report(args.out.expanduser(), metrics, annotation, label, about)
    if args.predictions:
        from .score import comparison_text, paired_difference, predictions_from_csv
        ours = annotation.extracted if extracted is None else extracted
        systems, differences = {"MoukhlijMatExtract": metrics}, {}
        for path in args.predictions:
            try:
                theirs = predictions_from_csv(path.expanduser(), annotation)
            except AnnotationError as error:
                print(error, file=sys.stderr)
                return 1
            systems[path.stem] = evaluate(annotation, theirs, seed=args.seed)
            differences[path.stem] = paired_difference(annotation, ours, theirs, seed=args.seed)
        paths["comparison"] = args.out.expanduser() / "comparison.md"
        paths["comparison"].write_text(comparison_text(systems, differences), encoding="utf-8")
        print(f"Systems compared: {paths['comparison']}")
    run.finish({"papers": metrics["papers"], "reference_values": metrics["gold"], "extracted_values": metrics["extracted"],
                "record_f1": metrics["levels"]["record"]["all"]["f1"], "value_f1": metrics["levels"]["value"]["all"]["f1"]},
               files=[p.name for p in paths.values()])
    for warning in annotation.warnings[:10]:
        print("warning:", warning)
    if len(annotation.warnings) > 10:
        print(f"warning: … and {len(annotation.warnings) - 10} more (see the report)")
    _print_summary(metrics)
    print(f"Report: {paths['report']}\nEvery number: {paths['metrics']}\nEvery error: {paths['errors']}")
    return 0


def _print_summary(metrics) -> None:
    def pct(x):
        return "  –  " if x is None else f"{100 * x:5.1f}"

    print(f"{metrics['papers']} papers, {metrics['gold']} reference values, {metrics['extracted']} extracted.")
    rows = [(f"{level} · {'all' if scope == 'all' else scope.replace('_', ' ')}", s)
            for level in ("record", "value") for scope, s in metrics["levels"][level].items()]
    width = max([24] + [len(name) for name, _ in rows]) + 2  # the longest name sets the column
    print(f"  {'':{width}}{'precision':>10}{'recall':>9}{'F1':>8}")
    for name, s in rows:
        print(f"  {name:{width}}{pct(s['precision']):>10}{pct(s['recall']):>9}{pct(s['f1']):>8}")


def run_agree(args) -> int:
    from .score import AnnotationError, agreement, read_annotation
    try:
        first, second = read_annotation(args.first.expanduser()), read_annotation(args.second.expanduser())
    except AnnotationError as error:
        print(error, file=sys.stderr)
        return 1
    result = agreement(first, second)
    if not result["papers"]:
        print("The two workbooks have no paper marked done by both.", file=sys.stderr)
        return 1

    def show(x, pct=True):
        return "–" if x is None else (f"{100 * x:.1f} %" if pct else f"{x:.3f}")

    print(f"{result['papers']} papers done by both, {result['rows']} extracted values judged by both.")
    print(f"  Cohen's kappa of the verdicts: {show(result['kappa'], pct=False)}   (raw agreement "
          f"{show(result['raw_agreement'])})")
    print(f"  F1 of one reference set against the other: value level {show(result['value_f1'])}, "
          f"record level {show(result['record_f1'])}")
    if result["confusion"]:
        print("  Verdicts (first / second): " + ", ".join(f"{k}: {v}" for k, v in sorted(result["confusion"].items())))
    return 0


def run_reference(args) -> int:
    import logging
    from LocalExtraction import runcontrol
    from . import reference as ref
    from .about import DEFAULT_DIR
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    base = DEFAULT_DIR / "reference"
    papers, output = base / "papers", base / "output"
    run = Run("reference comparison", base, settings={"databases": args.db, "fetch": not args.no_fetch,
                                                     "limit": args.limit})
    tables = {}
    for name in args.db:
        try:
            ref.download(name, base / "databases", refresh=args.refresh)
        except Exception as error:
            print(f"{ref.DATABASES[name]['name']} could not be downloaded: {error}", file=sys.stderr)
            continue
        tables[name] = ref.load(name, base / "databases")
        print(f"{ref.DATABASES[name]['name']}: {len(tables[name])} entries, {tables[name]['doi'].nunique()} papers "
              f"({ref.DATABASES[name]['license']})")
    if not tables:
        return 1
    dois = sorted({d for t in tables.values() for x in t["doi"] for d in ref.dois_of(x)})
    with runcontrol.ctrl_c_stops() as control:  # Ctrl-C: what was fetched and extracted is kept
        if args.no_fetch:
            fetched = ref.fetch_papers([], papers)
        else:
            print(f"Looking for the open copies of {len(dois)} papers (the ones tried before are skipped) …")
            fetched = ref.fetch_papers(dois, papers, limit=args.limit, stop_event=control)
        if any(papers.glob("*.pdf")):
            print("Extracting the papers fetched (only the new ones) …")
            ref.extract(papers, output, workers=args.workers, stop_event=control)
    files = ref.doi_of_files(papers)
    results = [ref.compare(table, output, files) for table in tables.values()]
    others = {}
    for csv_path in args.predictions:
        folder = ref.tool_output(csv_path.expanduser(), output, base / "tools" / csv_path.stem)
        others[csv_path.stem] = [ref.compare(table, folder, files) for table in tables.values()]
    base.mkdir(parents=True, exist_ok=True)
    text = ref.report(results, fetched, version(), others)
    (base / "reference_report.md").write_text(text, encoding="utf-8")
    import pandas as pd
    pd.concat([r.rows for r in results], ignore_index=True).to_csv(base / "reference_comparison.csv", index=False,
                                                                   encoding="utf-8-sig")
    run.finish({r.reference: {"entries": r.entries, "entries_read": r.entries_read, "material": r.material,
                              "record": r.record_loose, "record_strict": r.record_strict} for r in results},
               files=["reference_report.md", "reference_comparison.csv"])
    for r in results:
        share = lambda n: f"{100 * n / r.entries_read:.1f} %" if r.entries_read else "–"  # noqa: E731
        print(f"  {r.reference}: {r.papers_read} of {r.papers} papers read; of their {r.entries_read} entries, material "
              f"found {share(r.material)}, material and value {share(r.record_loose)} (within 2 %: {share(r.record_strict)})")
    for tool, rows in others.items():
        for r in rows:
            share = lambda n: f"{100 * n / r.entries_read:.1f} %" if r.entries_read else "–"  # noqa: E731
            print(f"  {tool} on {r.reference}: material found {share(r.material)}, material and value "
                  f"{share(r.record_loose)} (within 2 %: {share(r.record_strict)})")
    print(f"Report: {base / 'reference_report.md'}\nEvery entry: {base / 'reference_comparison.csv'}")
    return 0



def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    enter_project_home("eval")  # after the options are read: --help makes no folder
    return {"sheet": run_sheet, "score": run_score, "agree": run_agree,
            "reference": run_reference}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
