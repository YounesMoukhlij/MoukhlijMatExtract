# SelectingTopMaterial/cli.py
"""The command line of the selection.

    python -m SelectingTopMaterial                          every results folder of the project
    python -m SelectingTopMaterial --source WebScraping/web_output      one folder only
    python -m SelectingTopMaterial --origin experimental    measured values only
    python -m SelectingTopMaterial --policy conservative    a material is as good as its worst value
    python -m SelectingTopMaterial --by-phase               cubic and tetragonal LLZO apart
    python -m SelectingTopMaterial --top 10 --open          the first ten, and the report in the browser
    python -m SelectingTopMaterial gui                      the window

It ends with 0 when a ranking was written, 1 when there was nothing to rank or a file could not be
written, 2 when it was asked something it cannot do (an unknown option, a criteria file that is
wrong)."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from LocalExtraction.about import command_name, enter_project_home, version_text
from LocalExtraction.done import already_done, fingerprint, mark_done
from LocalExtraction.provenance import Run

from . import console, exporters, html_report, loader
from .about import DEFAULT_RESULTS, NAME, PROJECT_ROOT, VERSION
from .criteria import POLICIES, Criteria, CriteriaError
from .models import COMPONENTS, Filters, component_word
from .selection import select_from_each

FORMATS = ("csv", "xlsx", "json", "html")


def _record(run: Run, selections) -> None:
    """The run, in <out>/run_manifest.json (what was ranked, with what)."""
    try:
        run.finish({component: {"materials": len(s.materials), "values_used": s.values_used,
                                "values_read": s.values_read} for component, s in selections.items()})
    except OSError as error:
        print(f"  (the run could not be recorded: {error})", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=command_name("mme-rank", NAME),
        description="Ranks the materials of the MoukhlijMatExtract database by activation energy and sorts them "
                    "into the classes of criteria.toml (Superionic, Performant, Acceptable, Rejected) — one "
                    "ranking per transport component: bulk, grain boundary and total.",
        epilog="The database is only read. Each component's ranking is written into a folder of its own — "
               "SelectingTopMaterial/results/bulk/, grain_boundary/, total/ — with summary.csv beside them. "
               f"The window: {command_name('mme-rank', NAME)} gui ({command_name('mme-rank', NAME)} gui --help "
               "for its options). "
               "MoukhlijMatExtract (MME) — Created by Younes Moukhlij.")
    parser.add_argument("--source", "-s", nargs="+", action="extend", metavar="DIR",
                        help="Results folder(s) to read, the most trusted first (default: "
                             "LocalExtraction/local_output and WebScraping/web_output, whichever exist)")
    parser.add_argument("--out", "-o", default=str(DEFAULT_RESULTS), metavar="DIR",
                        help="Folder to write the ranking into (default: SelectingTopMaterial/results)")
    parser.add_argument("--criteria", metavar="FILE",
                        help="Criteria file to use instead of SelectingTopMaterial/criteria.toml")
    parser.add_argument("--policy", choices=tuple(POLICIES),
                        help="Which activation energy stands for a material that has several: "
                             + "; ".join(f"{name} = {meaning}" for name, meaning in POLICIES.items())
                             + " (default: the one of the criteria file)")
    parser.add_argument("--by-phase", action="store_true",
                        help="Rank the phases of a composition apart (cubic / tetragonal, β / γ) when the "
                             "database names them")

    values = parser.add_argument_group("which values take part")
    values.add_argument("--origin", choices=("experimental", "simulation"),
                        help="Only measured values, or only computed ones")
    values.add_argument("--attribution", choices=("this-work", "cited"),
                        help="Only the papers' own results, or only the values they cite")
    values.add_argument("--component", metavar="NAME",
                        help="Rank one transport component only: bulk, grain_boundary (or \"grain boundary\"), "
                             "total. By default each is ranked on its own, into a folder of its own")
    values.add_argument("--element", nargs="+", action="extend", metavar="SYMBOL", type=_element,
                        help="Only the materials that contain these elements (--element Na: the sodium conductors)")
    values.add_argument("--min-confidence", type=_confidence, default=0.0, metavar="0-1",
                        help="Only the values the extraction gave at least this confidence (default: all)")
    values.add_argument("--include-flagged", action="store_true",
                        help="Also rank the values the extraction flagged (plausibility \"check: …\"): outside "
                             "0.05–1.5 eV, or the transport of electrons or of another element than a conducting "
                             "ion. By default they are left out")

    shown = parser.add_argument_group("what is shown and written")
    shown.add_argument("--top", type=_positive, metavar="N",
                       help="Keep the first N materials that pass, in the terminal and in top_materials")
    shown.add_argument("--format", nargs="+", action="extend", choices=FORMATS, metavar="FORMAT",
                       help=f"Files to write: {', '.join(FORMATS)} (default: all of them)")
    shown.add_argument("--no-files", action="store_true", help="Show the ranking, write nothing")
    shown.add_argument("--open", action="store_true", help="Open the report in the browser once written")
    shown.add_argument("--quiet", "-q", action="store_true", help="Say nothing but what goes wrong")
    shown.add_argument("--no-color", action="store_true", help="No colours in the terminal")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Rank again even when nothing has changed since the last ranking written")
    parser.add_argument("--version", action="version", version=version_text("mme-rank"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["gui"]:
        from .gui import main as gui_main  # Tk is loaded only when the window is asked for
        return gui_main(argv[1:])
    args = build_parser().parse_args(argv)
    enter_project_home("rank")  # after the options are read: --help makes no folder
    _keep_printing(sys.stdout, sys.stderr)

    try:
        criteria = Criteria.load(args.criteria)
    except CriteriaError as error:
        return _fail(str(error), code=2)

    databases = [source_folder(name) for name in args.source] if args.source else loader.discover(PROJECT_ROOT)
    if not databases:
        return _fail(f"no results folder with {loader.TABLE} in {PROJECT_ROOT} "
                     f"(looked for {', '.join(name + '/' for name in loader.KNOWN_DATABASES)}).\n"
                     f"Run the extraction first (python -m LocalExtraction or python -m WebScraping), or name a folder with --source.")
    out_dir = Path(args.out).expanduser()
    if not args.no_files and (out_dir / loader.TABLE).exists():
        return _fail(f"{out_dir} is a database of MoukhlijMatExtract: the ranking is not written into a folder it "
                     f"reads. Choose another --out.", code=2)

    filters = Filters(min_confidence=args.min_confidence, origin=args.origin or "",
                      attribution=(args.attribution or "").replace("-", " "), component=args.component or "",
                      elements=tuple(dict.fromkeys(args.element or ())), include_flagged=args.include_flagged)
    # The same databases, criteria, options and code as the ranking already in --out: already done.
    settings = {"databases": [str(Path(d).resolve()) for d in databases], "criteria": repr(criteria),
                "policy": args.policy, "by_phase": args.by_phase, "filters": repr(filters), "top": args.top,
                "formats": sorted(args.format or FORMATS)}
    stamp = fingerprint(databases, settings, code=[Path(__file__).resolve().parent])
    when = None if args.force or args.no_files else already_done(out_dir, "rank", stamp)
    if when:
        if not args.quiet:
            print(f"\n  Already ranked: nothing has changed since the last ranking ({when}) — skipped.\n"
                  f"  The ranking is in {_shown(out_dir)} (add --force to rank again).")
        report = next((out_dir / c / "report.html" for c in COMPONENTS if (out_dir / c / "report.html").exists()), None)
        if args.open and report is not None:
            webbrowser.open(report.resolve().as_uri())
        return 0

    run = Run("ranking", out_dir, settings={**settings, "include_flagged": args.include_flagged,
                                            "min_confidence": args.min_confidence})
    selections = select_from_each(databases, criteria, root=PROJECT_ROOT, policy=args.policy,
                                  by_phase=args.by_phase, filters=filters)
    ranked = any(s.materials for s in selections.values())

    written_by: dict[str, list[Path]] = {}
    if ranked and not args.no_files:
        try:
            written_by = write_rankings(selections, out_dir, args.format or FORMATS, args.top)
        except OSError as error:
            return _fail(str(error))
        mark_done(out_dir, "rank", stamp, [p for paths in written_by.values() for p in paths])
        _record(run, selections)

    if not args.quiet or not ranked:
        stream = sys.stdout if ranked else sys.stderr
        colour = console.use_colour(stream, False if args.no_color else None)
        for component, selection in selections.items():
            stream.write(f"\n{'═' * 3} {component_word(component).capitalize()} transport {'═' * 40}\n")
            if selection.materials:
                stream.write(console.render(
                    selection, top=args.top, written=written_by.get(component, []),
                    out_dir=_shown(out_dir / component), colour=colour, width=console.terminal_width(stream)))
            else:
                stream.write(f"  No {component_word(component)} activation energy in the databases"
                             + ("" if selection.filters.describe() == f"{component_word(component)} transport"
                                else f" with these filters ({selection.filters.describe()})") + ".\n")
        if written_by.get("summary"):
            stream.write(f"\n  The components side by side: {_shown(out_dir)}summary.csv\n")
    if not ranked:
        first = next(iter(selections.values()))
        others = replace(first.filters, component="").describe()
        for report in first.databases:  # what each folder gave, and why nothing when nothing
            print(f"  Read {report.path}: {loader.describe(report)}", file=sys.stderr)
        print(f"\n{NAME}: none of the {first.values_read} values read passes the filters ({others})."
              if first.values_read else f"\n{NAME}: no activation energy to rank in these folders.", file=sys.stderr)
        return 1

    written = [p for paths in written_by.values() for p in paths]
    report = next((path for path in written if path.suffix == ".html"), None)
    if args.open and report:
        webbrowser.open(report.resolve().as_uri())
    elif args.open:
        print("  --open: no report was written (html is not among the formats asked for).", file=sys.stderr)
    return 0


# What a ranking of one component writes, and what earlier versions wrote at the top of the folder.
RANKING_FILES = ("top_materials.csv", "all_materials.csv", "values.csv", "selection.xlsx", "selection.json",
                 "report.html")


def write_rankings(selections: dict, out_dir: Path, formats: Sequence[str], top: int | None) -> dict[str, list[Path]]:
    """Each component's ranking in a folder of its own — results/bulk/, results/grain_boundary/,
    results/total/ — and summary.csv beside them. A component with nothing to rank has no folder
    (one left by an earlier ranking is taken away), and the one ranking earlier versions wrote at
    the top of the folder is taken away too: it mixed the components. Returns the files by
    component, and under "summary" the summary."""
    written: dict[str, list[Path]] = {}
    for component, selection in selections.items():
        folder = out_dir / component
        if selection.materials:
            written[component] = write_files(selection, folder, formats, top)
        elif folder.is_dir():
            for name in RANKING_FILES:
                (folder / name).unlink(missing_ok=True)
            try:
                folder.rmdir()
            except OSError:  # something else is in it: it stays
                pass
    for name in RANKING_FILES:
        (out_dir / name).unlink(missing_ok=True)
    written["summary"] = [exporters.write_summary(selections, out_dir)]
    return written


def write_files(selection, out_dir: Path, formats: Sequence[str], top: int | None) -> list[Path]:
    """The files asked for, in the order they are named in the terminal."""
    written: list[Path] = []
    if "csv" in formats:
        written += exporters.write_csv(selection, out_dir, top=top)
    if "xlsx" in formats:
        try:
            written.append(exporters.write_xlsx(selection, out_dir, top=top))
        except ImportError:
            print("  selection.xlsx was not written: it needs openpyxl (pip install openpyxl).", file=sys.stderr)
    if "json" in formats:
        written.append(exporters.write_json(selection, out_dir))
    if "html" in formats:
        written.append(html_report.write_html(selection, out_dir))
    return written


def source_folder(name: str) -> Path:
    """A folder as it was named: from where the command is run, otherwise from the project."""
    path = Path(name).expanduser()
    return path if path.exists() or path.is_absolute() else PROJECT_ROOT / path


def _shown(path: Path) -> str:
    """A folder as the terminal names it: from where the command is run, when it is under it."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve())) + "/"
    except ValueError:
        return str(path) + "/"


def _fail(message: str, code: int = 1) -> int:
    print(f"{NAME}: {message}", file=sys.stderr)
    return code


def _keep_printing(*streams) -> None:
    """A terminal that cannot show a character (≤, ◆ on an old Windows console) shows "?" in its
    place rather than stopping the program."""
    for stream in streams:
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def _positive(text: str) -> int:
    try:
        number = int(text)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of materials (1 or more)")
    return number


def _confidence(text: str) -> float:
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        number = -1.0
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a confidence (between 0 and 1)")
    return number


def _element(text: str) -> str:
    symbol = text.strip().capitalize()
    if symbol not in loader._ELEMENTS:
        raise argparse.ArgumentTypeError(f"{text!r} is not the symbol of an element (Li, Na, ...)")
    return symbol
