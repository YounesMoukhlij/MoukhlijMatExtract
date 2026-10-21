# WebScraping/cli.py
"""The command line of Project 2: search, review, fetch, extract. Run from the project root.

    python -m WebScraping                            search + screen (WebScraping/configs/sse.yaml), stop for your review
    python -m WebScraping --stage fetch              after the review: fetch what you approved, then extract it
    python -m WebScraping --check                    test the setup (network, API keys, folders) first
    python -m WebScraping --job my_job.yaml --limit 10
    python -m WebScraping --stage extract --rebuild  extract every fetched PDF again (fetches nothing, deletes nothing)
    python -m WebScraping gui                        the window

The extraction is that of Project 1 (LocalExtraction), into a folder of results of its own."""

import argparse
import logging
import os
import sys
from typing import List, Optional

from LocalExtraction.about import CREDIT_TEXT, FULL_NAME, print_banner
from LocalExtraction.cli import rebuild_if_asked
from LocalExtraction.exporter import UnreadableTable

from .about import DEFAULT_JOB, DEFAULT_OUTPUT, DESCRIPTION
from .job import load_env

_COMMANDS = ("run", "gui")


def _add_common(parser: argparse.ArgumentParser, job_default: Optional[str]) -> None:
    parser.add_argument("--job", default=job_default,
                        help=f"Job file (YAML): what to search for, which papers to keep, what to extract "
                             f"(default: {DEFAULT_JOB})")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT,
                        help=f"Directory to write the extracted database into (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--workers", "-w", type=int, default=4,
                        help="Number of PDFs to process in parallel (default: 4)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug-level logging")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m WebScraping",
        description="Project 2 of MoukhlijMatExtract: find papers online, fetch the legal copies into "
                    "WebScraping/papers/ and extract from them. run (the default): from this terminal. "
                    "gui: from a window.",
        epilog=CREDIT_TEXT,
    )
    commands = parser.add_subparsers(dest="command", metavar="{run,gui}")

    run = commands.add_parser("run", help=f"Search, review, fetch and extract into {DEFAULT_OUTPUT}/ (the default)")
    _add_common(run, DEFAULT_JOB)
    run.add_argument("--stage", choices=("discover", "fetch", "extract"), default="discover",
                     help="First stage to run. discover (default): search and screen, then stop for your "
                          "review if the job asks for one. fetch: after the review, fetch what you approved "
                          "and extract it. extract: only extract what is already fetched")
    run.add_argument("--yes", action="store_true", help="Approve every proposed paper without a review")
    run.add_argument("--limit", type=int, help="Fetch at most this many papers in this run")
    run.add_argument("--check", action="store_true", help="Test the setup (network, API keys, folders) and exit")
    run.add_argument("--probe-doi", help="With --check: an Elsevier DOI to test the Elsevier API key with")
    run.add_argument("--rebuild", action="store_true",
                     help="Extract every fetched PDF again instead of only the new ones. The present database "
                          "files are not deleted: they are moved to <output>/previous_<date>/")

    window = commands.add_parser("gui", help="The window: the same steps as buttons, the review in a table")
    _add_common(window, None)
    return parser.parse_args(argv)


def run_web(args: argparse.Namespace) -> int:
    """The stages of WebScraping/harvest.py, from the one asked for. Imported here so that the
    window and --help never load them."""
    from .doctor import check
    from .harvest import Harvest
    from .http import PoliteClient
    from .job import load_job

    try:
        job = load_job(args.job)
    except (OSError, ValueError) as error:
        logging.error(f"{args.job}: {error}")
        return 2
    if args.check:
        return check(job, PoliteClient(job.email()), args.probe_doi or "", os.path.join(args.output, "papers.csv"))
    try:
        return Harvest(job, args.output).run(start=args.stage, approve=args.yes, limit=args.limit,
                                             workers=args.workers, job_path=args.job)
    except UnreadableTable as error:  # nothing was written over: say which file, and how to go on
        logging.error(str(error))
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Without a command — `python -m WebScraping --stage fetch` — it means `run`.
    if not argv or argv[0] not in (*_COMMANDS, "-h", "--help"):
        argv = ["run", *argv]
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    print_banner(f"{FULL_NAME} · Web scraping", DESCRIPTION)
    load_env()  # ELSEVIER_API_KEY, MME_EMAIL, ... from WebScraping/.env

    if args.command == "gui":
        from .gui import main as gui_main
        gui_main(job_path=args.job, output_dir=args.output, workers=args.workers)
        return 0

    if not args.check:
        rebuild_if_asked(args.output, args.rebuild)
    return run_web(args)


if __name__ == "__main__":
    sys.exit(main())
