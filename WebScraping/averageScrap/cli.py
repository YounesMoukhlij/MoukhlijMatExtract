# WebScraping/cli.py
"""The command line of Project 2: search, review, fetch, extract. Works inside ~/MoukhlijMatExtract
(made with WebScraping/papers and WebScraping/web_output if missing), from wherever it is started.

    python -m WebScraping                            search + screen (configs/sse.yaml), stop for your review
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

from LocalExtraction import runcontrol
from LocalExtraction.about import CREDIT_TEXT, FULL_NAME, command_name, enter_project_home, print_banner, version_text
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
        prog=command_name("mme-web", "WebScraping"),
        description="Project 2 of MoukhlijMatExtract: find papers online, fetch the legal copies into "
                    "WebScraping/papers/ and extract from them. run (the default): from this terminal. "
                    "gui: from a window.",
        epilog=CREDIT_TEXT,
    )
    parser.add_argument("--version", action="version", version=version_text("mme-web"))
    commands = parser.add_subparsers(dest="command", metavar="{run,gui}")

    run = commands.add_parser("run", help=f"Search, review, fetch and extract into {DEFAULT_OUTPUT}/ (the default)")
    _add_common(run, DEFAULT_JOB)
    run.add_argument("--stage", choices=("discover", "fetch", "extract"), default="discover",
                     help="First stage to run. discover (default): search and screen, then stop for your "
                          "review if the job asks for one. fetch: after the review, fetch what you approved "
                          "and extract it. extract: only extract what is already fetched")
    run.add_argument("--yes", action="store_true", help="Approve every proposed paper without a review")
    run.add_argument("--limit", type=int, help="Fetch at most this many papers in this run")
    run.add_argument("--dois", nargs="?", const="", metavar="FILE",
                     help="Search with DOIs: take in the DOIs of a list (default: the list of mme-dois, "
                          "WebScraping/Fetch_DOIs/dois.csv), check them like the keyword results (OpenAlex record, "
                          "abstract, topic score), then fetch the legal open-access copies of those on topic and "
                          "extract them — no keyword search. (A plain run takes the job's doi_list in too.)")
    run.add_argument("--check", action="store_true", help="Test the setup (network, API keys, folders) and exit")
    run.add_argument("--probe-doi", help="With --check: an Elsevier DOI to test the Elsevier API key with")
    run.add_argument("--refresh", action="store_true",
                     help="Search again the queries already searched (by default a query a source answered "
                          "in the last 30 days is skipped)")
    run.add_argument("--rebuild", action="store_true",
                     help="Extract every fetched PDF again instead of only the new ones. The present database "
                          "files are not deleted: they are moved to <output>/previous_<date>/")

    window = commands.add_parser("gui", help="The window: the same steps as buttons, the review in a table")
    _add_common(window, None)
    return parser.parse_args(argv)


def run_web(args: argparse.Namespace) -> int:
    """The stages of WebScraping/harvest.py, from the one asked for. Imported here so that the
    window and --help never load them."""
    from .about import DEFAULT_JOB, ensure_default_job
    from .doctor import check
    from .harvest import Harvest
    from .http import PoliteClient
    from .job import load_job

    if args.job == DEFAULT_JOB:  # a fresh folder: make a starter configs/sse.yaml from the shipped one
        args.job = ensure_default_job(args.job)
    try:
        job = load_job(args.job)
    except (OSError, ValueError) as error:
        logging.error(f"{args.job}: {error}")
        return 2
    if args.check:
        return check(job, PoliteClient(job.email()), args.probe_doi or "", os.path.join(args.output, "papers.csv"))
    try:
        with runcontrol.ctrl_c_stops() as control:
            code = _run_stages(args, job, Harvest(job, args.output), control)
        if control.is_set():
            print(f"\n{runcontrol.STOPPED_BY_CTRL_C}")
            return 130
        return code
    except UnreadableTable as error:  # nothing was written over: say which file, and how to go on
        logging.error(str(error))
        return 1


def _run_stages(args: argparse.Namespace, job, harvest, control) -> int:
    """The stages asked for, stopped by `control` (Ctrl-C)."""
    if args.dois is not None:  # search with DOIs: the list as candidates, then download and extract
        from WebScraping.Fetch_DOIs.get_dois import OUTPUT
        listed = args.dois or str(OUTPUT)
        if not os.path.exists(listed) and not os.path.exists(os.path.splitext(listed)[0] + ".txt"):
            logging.error(f"There is no DOI list at {listed}: collect DOIs first with mme-dois.")
            return 2
        harvest.add_dois(listed, os.path.splitext(listed)[0] + ".txt")
        harvest.check_new()  # OpenAlex record, abstract, topic score — like the keyword results
        if control.is_set():
            return 0
        if job.screen.review and not args.yes:
            waiting = harvest.ledger.write_review(harvest.review_path)
            print(f"\nReview the candidates in {harvest.review_path} ({waiting} waiting for a decision), then fetch "
                  f"what you approved:\n    mme-web --job {args.job} --stage fetch\n(or add --yes to approve every "
                  "proposal without looking).")
            return 0
        if args.yes:
            harvest.screen(approve=True)
        return harvest.run(start="fetch", limit=args.limit, workers=args.workers, job_path=args.job,
                           stop_event=control)
    return harvest.run(start=args.stage, approve=args.yes, limit=args.limit,
                       workers=args.workers, job_path=args.job, refresh=args.refresh, stop_event=control)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Without a command — `python -m WebScraping --stage fetch` — it means `run`.
    if not argv or argv[0] not in (*_COMMANDS, "-h", "--help", "--version"):
        argv = ["run", *argv]
    args = parse_args(argv)
    enter_project_home("web", "dois")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    print_banner(f"{FULL_NAME} · Web scraping", DESCRIPTION)
    load_env()  # ELSEVIER_API_KEY, MME_EMAIL, ... from WebScraping/averageScrap/.env

    if args.command == "gui":
        from LocalExtraction.about import require_tk
        require_tk("mme-web gui")
        from WebScraping.webgui import main as gui_main  # the same window as `python -m WebScraping gui`
        gui_main(job_path=args.job, output_dir=args.output, workers=args.workers)
        return 0

    if not args.check and not rebuild_if_asked(args.output, args.rebuild):
        return 1
    return run_web(args)


if __name__ == "__main__":
    sys.exit(main())
