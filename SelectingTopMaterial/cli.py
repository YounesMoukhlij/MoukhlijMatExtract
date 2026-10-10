# SelectingTopMaterial/cli.py
"""The command line of the selection.

    python -m SelectingTopMaterial                          every results folder of the project
    python -m SelectingTopMaterial --source web_output      one folder only
    python -m SelectingTopMaterial --origin experimental    measured values only
    python -m SelectingTopMaterial --policy conservative    a material is as good as its worst value
    python -m SelectingTopMaterial --by-phase               cubic and tetragonal LLZO apart
    python -m SelectingTopMaterial --top 10 --open          the first ten, and the report in the browser

It ends with 0 when a ranking was written, 1 when there was nothing to rank or a file could not be
written, 2 when it was asked something it cannot do (an unknown option, a criteria file that is
wrong)."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from . import console, exporters, html_report, loader
from .about import DEFAULT_RESULTS, NAME, PROJECT_ROOT, VERSION
from .criteria import POLICIES, Criteria, CriteriaError
from .models import Filters
from .selection import select_from

FORMATS = ("csv", "xlsx", "json", "html")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"python -m {NAME}",
        description="Ranks the materials of the AutoMatExtract database by activation energy and sorts them "
                    "into the classes of criteria.toml (Superionic, Performant, Acceptable, Rejected).",
        epilog="The database is only read. The ranking is written into SelectingTopMaterial/results/.")
    parser.add_argument("--source", "-s", nargs="+", action="extend", metavar="DIR",
                        help="Results folder(s) to read, the most trusted first (default: local_output, "
                             "web_output and output of the project, whichever exist)")
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
                        help="Only one transport component: bulk, total, grain boundary, ...")
    values.add_argument("--element", nargs="+", action="extend", metavar="SYMBOL", type=_element,
                        help="Only the materials that contain these elements (--element Na: the sodium conductors)")
    values.add_argument("--min-confidence", type=_confidence, default=0.0, metavar="0-1",
                        help="Only the values the extraction gave at least this confidence (default: all)")

    shown = parser.add_argument_group("what is shown and written")
    shown.add_argument("--top", type=_positive, metavar="N",
                       help="Keep the first N materials that pass, in the terminal and in top_materials")
    shown.add_argument("--format", nargs="+", action="extend", choices=FORMATS, metavar="FORMAT",
                       help=f"Files to write: {', '.join(FORMATS)} (default: all of them)")
    shown.add_argument("--no-files", action="store_true", help="Show the ranking, write nothing")
    shown.add_argument("--open", action="store_true", help="Open the report in the browser once written")
    shown.add_argument("--quiet", "-q", action="store_true", help="Say nothing but what goes wrong")
    shown.add_argument("--no-color", action="store_true", help="No colours in the terminal")
    parser.add_argument("--version", action="version", version=f"{NAME} {VERSION}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _keep_printing(sys.stdout, sys.stderr)

    try:
        criteria = Criteria.load(args.criteria)
    except CriteriaError as error:
        return _fail(str(error), code=2)

    databases = [_source(name) for name in args.source] if args.source else loader.discover(PROJECT_ROOT)
    if not databases:
        return _fail(f"no results folder with {loader.TABLE} in {PROJECT_ROOT} "
                     f"(looked for {', '.join(name + '/' for name in loader.KNOWN_DATABASES)}).\n"
                     f"Run the extraction first (python main.py local), or name a folder with --source.")
    out_dir = Path(args.out).expanduser()
    if not args.no_files and (out_dir / loader.TABLE).exists():
        return _fail(f"{out_dir} is a database of AutoMatExtract: the ranking is not written into a folder it "
                     f"reads. Choose another --out.", code=2)

    filters = Filters(min_confidence=args.min_confidence, origin=args.origin or "",
                      attribution=(args.attribution or "").replace("-", " "), component=args.component or "",
                      elements=tuple(dict.fromkeys(args.element or ())))
    selection = select_from(databases, criteria, root=PROJECT_ROOT, policy=args.policy,
                            by_phase=args.by_phase, filters=filters)

    written: list[Path] = []
    if selection.materials and not args.no_files:
        try:
            written = _write(selection, out_dir, args.format or FORMATS, args.top)
        except OSError as error:
            return _fail(str(error))

    if not args.quiet or not selection.materials:
        stream = sys.stdout if selection.materials else sys.stderr
        stream.write(console.render(
            selection, top=args.top, written=written, out_dir=_shown(out_dir),
            colour=console.use_colour(stream, False if args.no_color else None),
            width=console.terminal_width(stream)))
    if not selection.materials:
        return 1

    report = next((path for path in written if path.suffix == ".html"), None)
    if args.open and report:
        webbrowser.open(report.resolve().as_uri())
    elif args.open:
        print("  --open: no report was written (html is not among the formats asked for).", file=sys.stderr)
    return 0


def _write(selection, out_dir: Path, formats: Sequence[str], top: int | None) -> list[Path]:
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


def _source(name: str) -> Path:
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
