# Crystal and Structure Classification/cli.py
"""The command line of the classification. Run from the project root.

    python "Crystal and Structure Classification"                   both databases → this folder
    python "Crystal and Structure Classification" --source WebScraping/web_output
    python "Crystal and Structure Classification" --out some/folder

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
from .database import AXES, classify, read, write


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f'python "{NAME}"',
        description="Classifies the materials of the MoukhlijMatExtract databases by crystal-structure type "
                    "(NASICON, LISICON, garnet, ...) and by structure family (oxide, sulfide, halide, ...), "
                    "and writes one database per class.",
        epilog="MoukhlijMatExtract (MME) — Created by Younes Moukhlij.")
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


def main(argv: Sequence[str] | None = None) -> int:
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
        named = [row for row in rows if not row["kind"].startswith("composition type")]
        for row in named:
            print(f"    {row[column]:<22} {row['n_materials']:>4} materials  {row['n_activation_energies']:>4} Ea  "
                  f"{row['n_papers']:>4} papers")
        rest = [row for row in rows if row["kind"].startswith("composition type")]
        if rest:
            print(f"    + {sum(r['n_materials'] for r in rest)} materials of no named structure type, by composition "
                  f"type ({len(rest)} of them, e.g. {', '.join(r[column] for r in rest[:3])}) in {axis}/composition_types/")
        print()
    print(f"  Every material with its two classes: {_shown(out_dir / 'all_materials.csv')}")
    return 0
