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
					enter_project_home, print_banner, version_text)
from . import runcontrol
from .exporter import StrictExporter, UnreadableTable
from .models import PaperData

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
	parser.add_argument("--version", action="version", version=version_text("mme-local"))
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

	`stop_event` is the step's Stop (the window's button; Ctrl-C in the terminal), and
	`progress_callback` gives the window its live per-paper feedback. `provenance`,
	`properties`, `require_material`, `origin` and `lookup` are described in NaLiXPipeline.
	"""
	if not os.path.isdir(input_dir):
		logging.error(f"Input directory not found: {input_dir}")
		return 1
	if is_outdated(output_dir):
		return 1

	from .pipeline import NaLiXPipeline  # loads the PDF reader and the language model: only to extract
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
		"to it as it is. Run the command in a terminal to choose: add the new articles to it (its tables are "
		"brought up to date) or start a new database (--rebuild: every PDF is extracted again) — in both cases "
		f"the present files are kept in {os.path.join(output_dir, 'previous_<date>')}.")
	return True


def main(argv: Optional[List[str]] = None) -> int:
	argv = list(sys.argv[1:] if argv is None else argv)
	# `python -m LocalExtraction --input <folder>` — without a command — means `extract`.
	if not argv or argv[0] not in (*_COMMANDS, "-h", "--help", "--version"):
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
		gui_main(input_dir=args.input, output_dir=args.output, workers=args.workers, lookup=not args.offline)
		return 0

	if not rebuild_if_asked(args.output, args.rebuild):
		return 1
	print(f"--> Processing papers from {os.path.abspath(args.input)} to {os.path.abspath(args.output)}")
	print(f"Using {args.workers} parallel workers")

	try:
		with runcontrol.ctrl_c_stops() as control:
			code = run_extraction(args.input, args.output, max_workers=args.workers, stop_event=control,
								  lookup=not args.offline)
		if control.is_set():
			print(f"\n{runcontrol.STOPPED_BY_CTRL_C}")
			return 130
		return code
	except UnreadableTable as error:  # nothing was written over: say which file, and how to go on
		logging.error(str(error))
		return 1


def rebuild_if_asked(output_dir: str, rebuild: bool) -> bool:
	"""What becomes of the database already in the folder. With --rebuild: a new one — the present files
	are moved to <output>/previous_<date>/, nothing is deleted, every PDF is extracted again. Without, and
	written by an earlier version: asked in a terminal — add the new articles to it (its tables brought up to
	date in place, a copy kept in previous_<date>/) or start a new one; not in a terminal (a script), it
	is kept and added to. Returns False when the run should not go on (asked, and stopped)."""
	if rebuild:
		kept = StrictExporter.archive(output_dir)
		if kept:
			print(f"--> A new database in {output_dir} (as asked); the previous files were moved to {kept}")
		return True
	if not StrictExporter.is_outdated(output_dir):
		return True
	can_add = StrictExporter.can_upgrade(output_dir)
	choice = "add" if can_add else "new"
	if sys.stdin.isatty():
		print(f"The database in {output_dir} was written by an earlier version of MoukhlijMatExtract.")
		if can_add:
			print("  [a] add the new articles to it — its tables are brought up to date (nothing is extracted "
				  "again), a copy of them as they were is kept in previous_<date>/")
		else:
			print("  (its tables are too different from this version's for new articles to be added to them)")
		print("  [n] start a new database — the present files are moved to previous_<date>/ (nothing is "
			  "deleted) and every PDF is extracted again")
		print("  [q] stop")
		options = "a/n/q" if can_add else "n/q"
		while True:
			answer = input(f"Your choice ({options}): ").strip().lower()[:1]
			if answer in ("a", "n", "q") and (answer != "a" or can_add):
				break
		if answer == "q":
			print("Stopped: nothing was changed.")
			return False
		choice = "add" if answer == "a" else "new"
	if choice == "add":
		kept = StrictExporter.upgrade(output_dir)
		print(f"--> The database of {output_dir} was brought up to date and the new articles are added to it; "
			  f"its files as they were are in {kept}")
	else:
		kept = StrictExporter.archive(output_dir)
		print(f"--> A new database in {output_dir} (the previous one was written by an earlier version of "
			  f"MoukhlijMatExtract and cannot take new articles); the previous files were moved to {kept}")
	return True


if __name__ == "__main__":
	sys.exit(main())
