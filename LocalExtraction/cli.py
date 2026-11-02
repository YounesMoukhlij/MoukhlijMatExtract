#!/usr/bin/env python3
# LocalExtraction/cli.py
"""The command line of Project 1: the PDFs of a folder into a database. Works inside
~/MoukhlijMatExtract (made with LocalExtraction/papers and LocalExtraction/local_output if missing),
from wherever it is started.

Usage:
	MoukhlijMatExtract (MME) — author: Younes Moukhlij
	mme-local  /  python -m LocalExtraction          (same as: python -m LocalExtraction extract)
	python -m LocalExtraction --input LocalExtraction/papers --output LocalExtraction/local_output --workers 4
	python -m LocalExtraction --input /path/to/pdfs --output /path/to/database -v
	python -m LocalExtraction --rebuild              (extract every PDF again; the present files are kept aside)
	python -m LocalExtraction --offline              (do not complete the papers' metadata from OpenAlex)
	python -m LocalExtraction gui                    (the window)
"""

import argparse
import logging
import os
import sys
import threading
from typing import Callable, Dict, Iterable, List, Optional

from .about import (CREDIT_TEXT, command_name, DEFAULT_INPUT, DEFAULT_OUTPUT, DESCRIPTION, FULL_NAME, PROJECT_HOME,
					enter_project_home, print_banner)
from .exporter import StrictExporter, UnreadableTable
from .models import PaperData
from .pipeline import NaLiXPipeline

_COMMANDS = ("extract", "gui")


def _add_folders(parser: argparse.ArgumentParser) -> None:
	parser.add_argument("--input", "-i", default=DEFAULT_INPUT,
						help=f"Directory containing input PDFs, relative to {PROJECT_HOME} (default: {DEFAULT_INPUT})")
	parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT,
						help=f"Directory to write the extracted database into, relative to {PROJECT_HOME} "
							 f"(default: {DEFAULT_OUTPUT})")
	parser.add_argument("--workers", "-w", type=int, default=4,
						help="Number of PDFs to process in parallel (default: 4)")
	parser.add_argument("--verbose", "-v", action="store_true",
						help="Enable debug-level logging")
	parser.add_argument("--offline", action="store_true",
						help="Do not complete the papers' title, authors, journal, DOI, year and license from OpenAlex")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		prog=command_name("mme-local", "LocalExtraction"),
		description="Project 1 of MoukhlijMatExtract: extract structured battery-materials data from the PDFs in a "
					"folder. extract (the default): from this terminal. gui: from a window.",
		epilog=CREDIT_TEXT,
	)
	commands = parser.add_subparsers(dest="command", metavar="{extract,gui}")

	extract = commands.add_parser("extract", help=f"Extract from the PDFs in a folder into {DEFAULT_OUTPUT}/ (the default)")
	_add_folders(extract)
	extract.add_argument("--rebuild", action="store_true",
						 help="Extract every PDF again instead of only the new ones. The present database files "
							  "are not deleted: they are moved to <output>/previous_<date>/")

	window = commands.add_parser("gui", help="The window: the same extraction, with its results shown as they land")
	_add_folders(window)
	return parser.parse_args(argv)


def run_extraction(input_dir: str, output_dir: str, max_workers: int = 4,
					stop_event: Optional[threading.Event] = None,
					progress_callback: Optional[Callable[[str, Optional[PaperData]], None]] = None,
					provenance: Optional[Callable[[str], Dict[str, str]]] = None,
					properties: Optional[Iterable[str]] = None, require_material: bool = False,
					origin: str = "local", lookup: bool = True) -> int:
	"""Shared pipeline entry point used by both gates — the terminal (`main()`) and the window
	(`LocalExtraction/gui/panel.py`) — so the two never drift into two different ways of running the same extraction.

	`stop_event`/`progress_callback` are optional and unused by the plain CLI path — they exist
	so the window can request an early stop and get live per-paper feedback. `provenance`,
	`properties`, `require_material`, `origin` and `lookup` are described in NaLiXPipeline.
	"""
	if not os.path.isdir(input_dir):
		logging.error(f"Input directory not found: {input_dir}")
		return 1
	if is_outdated(output_dir):
		return 1

	pipeline = NaLiXPipeline(input_dir=input_dir, output_dir=output_dir, provenance=provenance,
							 properties=properties, require_material=require_material, origin=origin, lookup=lookup)
	pipeline.execute(max_workers=max_workers, stop_event=stop_event, progress_callback=progress_callback)
	return 0


def is_outdated(output_dir: str) -> bool:
	"""Says so, and how to go on, when the output folder holds a database of an earlier version:
	its tables have other columns, so new papers cannot be added to it."""
	if not StrictExporter.is_outdated(output_dir):
		return False
	logging.error(
		f"The database in {output_dir} was written by an earlier version of MoukhlijMatExtract and has other columns "
		"(for one, activation energies and migration barriers were two properties). New papers cannot be added "
		"to it. Extract your PDFs again with --rebuild — nothing is downloaded again, and the present files are "
		f"kept in {os.path.join(output_dir, 'previous_<date>')} — or choose another --output folder.")
	return True


def main(argv: Optional[List[str]] = None) -> int:
	argv = list(sys.argv[1:] if argv is None else argv)
	# `python -m LocalExtraction --input <folder>` — without a command — means `extract`.
	if not argv or argv[0] not in (*_COMMANDS, "-h", "--help"):
		argv = ["extract", *argv]
	args = parse_args(argv)
	enter_project_home("local")

	logging.basicConfig(
		level=logging.DEBUG if args.verbose else logging.INFO,
		format="%(asctime)s [%(levelname)s] %(message)s",
		datefmt="%H:%M:%S",
	)

	print_banner(f"{FULL_NAME} · Local extraction", DESCRIPTION)

	if args.command == "gui":
		from .gui import main as gui_main
		gui_main(input_dir=args.input, output_dir=args.output, workers=args.workers)
		return 0

	rebuild_if_asked(args.output, args.rebuild)
	print(f"--> Processing papers from {os.path.abspath(args.input)} to {os.path.abspath(args.output)}")
	print(f"Using {args.workers} parallel workers")

	try:
		return run_extraction(args.input, args.output, max_workers=args.workers, lookup=not args.offline)
	except UnreadableTable as error:  # nothing was written over: say which file, and how to go on
		logging.error(str(error))
		return 1


def rebuild_if_asked(output_dir: str, rebuild: bool) -> None:
	"""Moves the database aside to be extracted again: when asked, and when it was written by an
	earlier version (its tables have other columns, so nothing can be added to it). Nothing is
	deleted: the files go to <output>/previous_<date>/."""
	outdated = StrictExporter.is_outdated(output_dir)
	if not (rebuild or outdated):
		return
	kept = StrictExporter.archive(output_dir)
	if kept:
		why = "it was written by an earlier version of MoukhlijMatExtract" if outdated and not rebuild else "as asked"
		print(f"--> Rebuilding the database of {output_dir} ({why}); the previous files were moved to {kept}")


if __name__ == "__main__":
	sys.exit(main())
