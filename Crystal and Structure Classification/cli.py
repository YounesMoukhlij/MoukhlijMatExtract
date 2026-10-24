# Crystal and Structure Classification/cli.py
"""The command line of the classification. Run from the project root.

    python "Crystal and Structure Classification"                   both databases → this folder
    python "Crystal and Structure Classification" --source WebScraping/web_output
    python "Crystal and Structure Classification" --out some/folder
    python "Crystal and Structure Classification" gui                the window

It reads LocalExtraction/local_output and WebScraping/web_output (whichever exist) and writes:

    crystal_structure/<type>/       NASICON, LISICON, garnet, argyrodite, ... one database each
    structure_families/<family>/    oxide, sulfide, halide, oxyhalide, ...   one database each
    all_materials.csv               every material with its two classes"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .about import CRYSTAL_STRUCTURE, DEFAULT_OUT, DEFAULT_SOURCES, NAME, PROJECT_ROOT, STRUCTURE_FAMILIES
from .classify import COMPONENT_WORDS, NO_FAMILY
from .database import AXES, BY_COMPONENT, classify, read, write


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f'python "{NAME}"',
        description="Classifies the materials of the MoukhlijMatExtract databases by crystal-structure type "
                    "(NASICON, LISICON, garnet, ...) and by structure family (oxide, sulfide, halide, ...), "
                    "and writes one database per class.",
        epilog=f'The window: python "{NAME}" gui. MoukhlijMatExtract (MME) — Created by Younes Moukhlij.')
    parser.add_argument("--source", "-s", nargs="+", action="extend", metavar="DIR",
                        help="Database folder(s) to read, the most trusted first (default: "
                             "LocalExtraction/local_output and WebScraping/web_output, whichever exist)")
    parser.add_argument("--out", "-o", default=str(DEFAULT_OUT), metavar="DIR",
                        help=f"Folder to write the classes into (default: {NAME}/)")
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
    if argv[:1] == ["gui"]:  # the window: python "Crystal and Structure Classification" gui
        from .gui import main as window
        return window(argv[1:])
    args = build_parser().parse_args(argv)
    folders = [_folder(name) for name in args.source] if args.source else list(DEFAULT_SOURCES)
    out_dir = Path(args.out).expanduser()

    sources = []
    for folder in folders:
        source = read(folder)
        if source is None:
            print(f"  {_shown(folder)}: no database here (no materials.csv) — skipped", file=sys.stderr)
            continue
        if source.path.resolve() == out_dir.resolve():
            print(f"{NAME}: {out_dir} is a database it reads: choose another --out.", file=sys.stderr)
            return 2
        sources.append(source)
        print(f"  Read {_shown(folder)}: {len(source.tables['materials'])} material rows, "
              f"{len(source.tables['activation_energy'])} activation energies")
    if not sources:
        print(f"{NAME}: no database to classify. Run the extraction first "
              "(python -m LocalExtraction or python -m WebScraping), or name one with --source.", file=sys.stderr)
        return 1

    classified = classify(sources)
    summaries = write(classified, out_dir)
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
