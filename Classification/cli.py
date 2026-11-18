# Classification/cli.py
"""The command line of the classification. Works inside ~/MoukhlijMatExtract (made with
Classification/crystal_structure and Classification/structure_families if missing), from wherever it is started.

    python -m Classification                   both databases → this folder
    python -m Classification --source WebScraping/web_output
    python -m Classification --out some/folder
    python -m Classification gui                the window

It reads LocalExtraction/local_output and WebScraping/web_output (whichever exist) and writes:

    crystal_structure/<type>/       NASICON, LISICON, garnet, argyrodite, ... one database each
    structure_families/<family>/    oxide, sulfide, halide, oxyhalide, ...   one database each
    all_materials.csv               every material with its two classes"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from LocalExtraction.about import command_name, enter_project_home, version_text
from LocalExtraction.done import already_done, fingerprint, mark_done
from LocalExtraction.provenance import Run

from .about import CRYSTAL_STRUCTURE, DEFAULT_OUT, DEFAULT_SOURCES, NAME, PACKAGE_DIR, PROJECT_ROOT, STRUCTURE_FAMILIES
from .classify import COMPONENT_WORDS, NO_FAMILY
from .database import AXES, BY_COMPONENT, classify, partly_rebuilt, read, write


def classify_stamp(sources) -> str:
    """The fingerprint of a classification: the databases read and this code."""
    return fingerprint([source.path for source in sources], {"sources": [str(s.path.resolve()) for s in sources]},
                       code=[PACKAGE_DIR])


def classify_run(sources, out_dir: Path) -> Run:
    return Run("classification", out_dir, settings={"sources": [str(s.path.resolve()) for s in sources],
                                                   "out": str(Path(out_dir).resolve())})


def record_classes(out_dir: Path, sources, run: Run, classified) -> None:
    """Says what a classification wrote into `out_dir`: the next one of the same databases is skipped, and the run is in
    run_manifest.json. Whoever writes the class folders — the command or the window — records them, or the classes of
    other databases would be taken for those of the stamp."""
    out_dir = Path(out_dir)
    mark_done(out_dir, "classify", classify_stamp(sources),
              [out_dir / "all_materials.csv", *(out_dir / axis for axis, _, _ in AXES)])
    try:
        run.finish({"materials": len(classified.materials)})
    except OSError as error:
        print(f"  (the run could not be recorded: {error})", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=command_name("mme-classify", "Classification"),
        description="Classifies the materials of the MoukhlijMatExtract databases by crystal-structure type "
                    "(NASICON, LISICON, garnet, ...) and by structure family (oxide, sulfide, halide, ...), "
                    "and writes one database per class.",
        epilog=f"The window: {command_name('mme-classify', 'Classification')} gui. "
               "MoukhlijMatExtract (MME) — Created by Younes Moukhlij.")
    parser.add_argument("--version", action="version", version=version_text("mme-classify"))
    parser.add_argument("--source", "-s", nargs="+", action="extend", metavar="DIR",
                        help="Database folder(s) to read, the most trusted first (default: "
                             "LocalExtraction/local_output and WebScraping/web_output, whichever exist)")
    parser.add_argument("--out", "-o", default=str(DEFAULT_OUT), metavar="DIR",
                        help="Folder to write the classes into (default: Classification/)")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Classify again even when the databases have not changed since the last run")
    return parser


def _folder(name: str) -> Path:
    path = Path(name).expanduser()
    return path if path.exists() or path.is_absolute() else PROJECT_ROOT / path


def _shown(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _count(n: int, word: str) -> str:
    return f"{n:>4} {word}{'' if n == 1 else 's'}" + (" " if n == 1 else "")


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["gui"]:  # the window: python -m Classification gui
        from LocalExtraction.about import require_tk
        require_tk("mme-classify gui")
        from .gui import main as window
        return window(argv[1:])
    args = build_parser().parse_args(argv)
    enter_project_home("classify")  # after the options are read: --help makes no folder
    folders = [_folder(name) for name in args.source] if args.source else list(DEFAULT_SOURCES)
    out_dir = Path(args.out).expanduser()

    sources = []
    for folder in folders:
        source = read(folder)
        if source is None:
            why = "its rebuild is not finished — run that part again" if partly_rebuilt(folder) else \
                "no database here (no materials.csv)"
            print(f"  {_shown(folder)}: {why} — skipped", file=sys.stderr)
            continue
        if source.path.resolve() == out_dir.resolve():
            print(f"{NAME}: {out_dir} is a database it reads: choose another --out.", file=sys.stderr)
            return 2
        sources.append(source)
        print(f"  Read {_shown(folder)}: {len(source.tables['materials'])} material rows, "
              f"{len(source.tables['activation_energy'])} activation energies")
        if partly_rebuilt(folder):
            print(f"  Warning: {_shown(folder)} is only partly rebuilt (a run was stopped): run that part again "
                  "to classify all its papers.", file=sys.stderr)
    if not sources:
        print(f"{NAME}: no database to classify. Run the extraction first "
              "(python -m LocalExtraction or python -m WebScraping), or name one with --source.", file=sys.stderr)
        return 1

    # The same databases, classified by the same code into the same folder: already done.
    stamp = classify_stamp(sources)
    when = None if args.force else already_done(out_dir, "classify", stamp)
    if when:
        print(f"\n  Already classified: the databases have not changed since the last run ({when}) — skipped.\n"
              f"  The classes are in {_shown(out_dir)}/ (add --force to classify again).")
        return 0

    run = classify_run(sources, out_dir)
    classified = classify(sources)
    summaries = write(classified, out_dir)
    record_classes(out_dir, sources, run, classified)
    print(f"\n  {len(classified.materials)} materials classified into {_shown(out_dir)}/\n")
    for axis, _, column in AXES:
        title = {CRYSTAL_STRUCTURE: "Crystal structure", STRUCTURE_FAMILIES: "Structure families"}[axis]
        print(f"  {title} ({axis}/)")
        rows = summaries[axis].to_dict("records")
        subs = summaries[f"{axis}/{BY_COMPONENT}"]
        for row in rows:
            print(f"    {row[column]:<26} {_count(row['n_materials'], 'material')}  {row['n_activation_energies']:>4} Ea  "
                  f"{_count(row['n_papers'], 'paper')}")
            mine = subs[subs[column] == row[column]].to_dict("records")
            for index, sub in enumerate(mine):  # its sub-classes: bulk, grain boundary, total
                branch = "└─" if index == len(mine) - 1 else "├─"
                word = COMPONENT_WORDS.get(sub["component"], sub["component"])
                lowest = f"lowest {sub['min_eV']} eV ({sub['min_material']})" if sub["n_values"] else "no activation energy"
                print(f"      {branch} {word:<21} {_count(sub['n_materials'], 'material')}  {sub['n_values']:>4} Ea  {lowest}")
        if axis == CRYSTAL_STRUCTURE:
            none = sum(1 for m in classified.materials.values() if m.structure_type == NO_FAMILY)
            if none:
                print(f"    + {none} materials of no known crystal family: in all_materials.csv and in their "
                      f"structure family, with their composition type")
        print()
    print(f"  Every material with its two classes: {_shown(out_dir / 'all_materials.csv')}")
    return 0
