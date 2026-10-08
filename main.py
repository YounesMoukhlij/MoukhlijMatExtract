#!/usr/bin/env python3
"""CLI entry point for AutoMatExtract.

Usage:
	author - Younes Moukhlij
	python main.py                                   (same as: python main.py local)
	python main.py local --input papers --output output --workers 4
	python main.py local --input /path/to/pdfs --output /path/to/database -v
	python main.py --gui
	python main.py web --job configs/sse.yaml        (search the web, stop for your review)
	python main.py web --job configs/sse.yaml --stage fetch
	python main.py web --job configs/sse.yaml --check
	python main.py both --job configs/sse.yaml       (the web project, then your own PDFs, into one database)
	python main.py both --job configs/sse.yaml --stage extract --rebuild
	                                                 (extract everything again; fetches nothing, deletes nothing)
"""

import argparse
import logging
import os
import sys
import threading
from typing import Callable, Dict, Iterable, List, Optional

from exporter import StrictExporter
from models import PaperData
from pipeline import NaLiXPipeline

_CREDIT_TEXT = ("AutoMatExtract — Created by Younes Moukhlij "
				"(Software Engineering student at 1337 Coding School, "
				"PhD researcher at FPK, USMS)")

# Shown alongside _CREDIT_TEXT at startup, in both the CLI banner and the GUI's header —
# kept here (rather than duplicated in gui.py) so the two never drift apart.
_PROJECT_DESCRIPTION = (
	"Turns a folder of battery/materials-science PDFs into a structured, queryable database: "
	"parses text, tables, figures and equations (with OCR fallback for scanned pages), extracts "
	"materials and their properties, and exports linked CSV, Excel and JSON."
)


def _print_banner() -> None:
	"""Prints a small decorated header to the console: project name, one-line description, and
	author credit (see _CREDIT_TEXT for the plain-text version used in --help, where box-drawing
	characters would look out of place)."""
	import textwrap

	title = "AutoMatExtract"
	body_lines = (
		textwrap.wrap(_PROJECT_DESCRIPTION, width=58)
		+ [""]
		+ [
			"Younes Moukhlij",
			"Software Engineering student · 1337 Coding School",
			"PhD Researcher · FPK, USMS",
		]
	)
	width = max(len(title), *(len(l) for l in body_lines)) + 4

	print("╭" + "─" * width + "╮")
	print("│ " + title.center(width - 2) + " │")
	print("├" + "─" * width + "┤")
	for l in body_lines:
		print("│ " + l.center(width - 2) + " │")
	print("╰" + "─" * width + "╯")


_COMMANDS = ("local", "web", "both")


def _add_common(parser: argparse.ArgumentParser) -> None:
	parser.add_argument("--output", "-o", default="output",
						help="Directory to write the extracted database into (default: output)")
	parser.add_argument("--workers", "-w", type=int, default=4,
						help="Number of PDFs to process in parallel (default: 4)")
	parser.add_argument("--verbose", "-v", action="store_true",
						help="Enable debug-level logging")
	parser.add_argument("--rebuild", action="store_true",
						help="Extract every PDF again instead of only the new ones. The present database files "
							 "are not deleted: they are moved to <output>/previous_<date>/")


def _add_local(parser: argparse.ArgumentParser, gui: bool) -> None:
	parser.add_argument("--input", "-i", default="papers",
						help="Directory containing input PDFs (default: papers)")
	if gui:
		parser.add_argument("--gui", action="store_true",
							help="Launch the desktop GUI instead of running from the command line")


def _add_web(parser: argparse.ArgumentParser) -> None:
	parser.add_argument("--job", help="Job file (YAML): what to search for, which papers to keep, what to "
									  "extract — see configs/sse.yaml")
	parser.add_argument("--stage", choices=("discover", "fetch", "extract"), default="discover",
						help="First stage to run. discover (default): search and screen, then stop for your "
							 "review if the job asks for one. fetch: after the review, fetch what you approved "
							 "and extract it. extract: only extract what is already fetched")
	parser.add_argument("--yes", action="store_true",
						help="Approve every proposed paper without a review")
	parser.add_argument("--limit", type=int,
						help="Fetch at most this many papers in this run")
	parser.add_argument("--check", action="store_true",
						help="Test the setup (network, API keys, folders) and exit")
	parser.add_argument("--probe-doi",
						help="With --check: an Elsevier DOI to test the Elsevier API key with")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="AutoMatExtract has two projects behind one gate. local: extract structured "
					"battery-materials data from the PDFs in a folder. web: find papers online, fetch the "
					"legal copies into papers/web/ and extract from them. both: run the two into one "
					"database. Without a command, local runs.",
		epilog=_CREDIT_TEXT,
	)
	commands = parser.add_subparsers(dest="command", metavar="{local,web,both}")

	local = commands.add_parser("local", help="Project 1: extract from the PDFs in a folder (the default)")
	_add_local(local, gui=True)
	_add_common(local)

	web = commands.add_parser("web", help="Project 2: search the web, fetch the papers, extract from them")
	_add_web(web)
	_add_common(web)

	both = commands.add_parser("both", help="Project 2 (up to your review), then Project 1, into one database")
	_add_local(both, gui=False)
	_add_web(both)
	_add_common(both)
	return parser.parse_args(argv)


def run_extraction(input_dir: str, output_dir: str, max_workers: int = 4,
					stop_event: Optional[threading.Event] = None,
					progress_callback: Optional[Callable[[str, Optional[PaperData]], None]] = None,
					provenance: Optional[Callable[[str], Dict[str, str]]] = None,
					properties: Optional[Iterable[str]] = None, require_material: bool = False,
					origin: str = "local") -> int:
	"""Shared pipeline entry point used by both the CLI (`main()`) and the GUI (`gui.py`), so
	the two never drift into two different ways of running the same extraction.

	`stop_event`/`progress_callback` are optional and unused by the plain CLI path — they exist
	so the GUI can request an early stop and get live per-paper feedback. `provenance`,
	`properties`, `require_material` and `origin` are described in NaLiXPipeline.
	"""
	if not os.path.isdir(input_dir):
		logging.error(f"Input directory not found: {input_dir}")
		return 1
	if _is_outdated(output_dir):
		return 1

	pipeline = NaLiXPipeline(input_dir=input_dir, output_dir=output_dir, provenance=provenance,
							 properties=properties, require_material=require_material, origin=origin)
	pipeline.execute(max_workers=max_workers, stop_event=stop_event, progress_callback=progress_callback)
	return 0


def _is_outdated(output_dir: str) -> bool:
	"""Says so, and how to go on, when the output folder holds a database of an earlier version:
	its tables have other columns, so new papers cannot be added to it."""
	if not StrictExporter.is_outdated(output_dir):
		return False
	logging.error(
		f"The database in {output_dir} was written by an earlier version of AutoMatExtract and has other columns "
		"(for one, activation energies and migration barriers were two properties). New papers cannot be added "
		"to it. Extract your PDFs again with --rebuild — nothing is downloaded again, and the present files are "
		f"kept in {os.path.join(output_dir, 'previous_<date>')} — or choose another --output folder.")
	return True


def run_web(args: argparse.Namespace) -> int:
	"""Project 2: see web/harvest.py. Imported here so that running Project 1 never loads it."""
	from web.doctor import check
	from web.harvest import Harvest
	from web.http import PoliteClient
	from web.job import load_env, load_job

	load_env()  # ELSEVIER_API_KEY, AUTOMATEXTRACT_EMAIL, ... from a .env file next to main.py
	if not args.job:
		logging.error("The web project needs a job file: --job configs/sse.yaml")
		return 2
	try:
		job = load_job(args.job)
	except (OSError, ValueError) as error:
		logging.error(f"{args.job}: {error}")
		return 2
	if args.check:
		return check(job, PoliteClient(job.email()), args.probe_doi or "", os.path.join(args.output, "papers.csv"))
	return Harvest(job, args.output).run(start=args.stage, approve=args.yes, limit=args.limit,
										 workers=args.workers, job_path=args.job)


def main(argv: Optional[List[str]] = None) -> int:
	argv = list(sys.argv[1:] if argv is None else argv)
	# `python main.py --input papers` — the way Project 1 has always been run — means `local`.
	if not argv or argv[0] not in (*_COMMANDS, "-h", "--help"):
		argv = ["local", *argv]
	args = parse_args(argv)

	logging.basicConfig(
		level=logging.DEBUG if args.verbose else logging.INFO,
		format="%(asctime)s [%(levelname)s] %(message)s",
		datefmt="%H:%M:%S",
	)

	_print_banner()

	if args.rebuild:
		kept = StrictExporter.archive(args.output)
		if kept:
			print(f"--> Rebuilding the database; the previous one was moved to {kept}")
	elif not getattr(args, "check", False) and not getattr(args, "gui", False) and _is_outdated(args.output):
		return 1

	if args.command == "web":
		return run_web(args)

	if args.command == "both":
		code = run_web(args)
		if code:
			return code
		print(f"--> Processing papers from {args.input} to {args.output}")
		return run_extraction(args.input, args.output, max_workers=args.workers)

	if args.gui:
		from gui import main as gui_main
		gui_main()
		return 0

	print(f"--> Processing papers from {args.input} to {args.output}")
	print(f"Using {args.workers} parallel workers")

	return run_extraction(args.input, args.output, max_workers=args.workers)


if __name__ == "__main__":
	sys.exit(main())
