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
from LocalExtraction.about import CREDIT_TEXT, FULL_NAME, command_name, enter_project_home, found_here, print_banner, version_text
from LocalExtraction.cli import rebuild_if_asked
from LocalExtraction.exporter import UnreadableTable

from .about import DEFAULT_JOB, DEFAULT_OUTPUT, DESCRIPTION, output_of
from .job import load_env

_COMMANDS = ("run", "gui", "coverage", "update")


def _add_common(parser: argparse.ArgumentParser, job_default: Optional[str]) -> None:
    parser.add_argument("--job", default=job_default,
                        help=f"Job file (YAML): what to search for, which papers to keep, what to extract "
                             f"(default: {DEFAULT_JOB})")
    parser.add_argument("--output", "-o", default=None,
                        help=f"Directory to write the extracted database into (default: the job's own, beside its "
                             f"PDF folder — {DEFAULT_OUTPUT} for WebScraping/papers, WebScraping/web_output_NAME for "
                             f"WebScraping/papers_NAME — so that two jobs never share a database)")
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

    run = commands.add_parser("run", help="Search, review, fetch and extract into the job's results folder (the default)")
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
    run.add_argument("--rescreen", action="store_true",
                     help="First decide again, with the job's screening settings of now, the papers screened before and "
                          "not downloaded yet (after a word was changed, or screen.propose_closed set to true). A yes "
                          "or no set by hand in the review list is decided again too")
    run.add_argument("--refresh", action="store_true",
                     help="Search again the queries already searched (by default a query a source answered "
                          "in the last 30 days is skipped)")
    run.add_argument("--snowball", action="store_true",
                     help="Also follow the citations of the papers kept, for this run (search.snowball in the job "
                          "file): OpenAlex gives the papers each one cites and the papers citing it, screened like "
                          "the others")
    run.add_argument("--update", action="store_true",
                     help="Search only for the papers published since this job's last search (from that year on: "
                          "the sources take years), then screen, download and extract as usual — to keep a "
                          "database current. A job never searched is searched in full")
    run.add_argument("--rebuild", action="store_true",
                     help="Extract every fetched PDF again instead of only the new ones. The present database "
                          "files are not deleted: they are moved to <output>/previous_<date>/")

    window = commands.add_parser("gui", help="The window: the same steps as buttons, the review in a table")
    _add_common(window, None)

    update = commands.add_parser("update", help="Every job searched before, brought up to date in turn: run "
                                                 "--update for each (with --all, every job never run too)")
    update.add_argument("--yes", action="store_true",
                        help="Approve every paper proposed without a review, for jobs that ask for one")
    update.add_argument("--all", action="store_true",
                        help="Also every job never run: searched in full, the whole literature of every family and "
                             "domain in one command (best with --yes, so that nothing waits for a review)")
    update.add_argument("--workers", "-w", type=int, default=4, help="PDFs read at once while extracting")
    update.add_argument("--verbose", "-v", action="store_true", help="Enable debug-level logging")

    reach = commands.add_parser("coverage", help="How far each job's papers went (found, proposed, downloaded, "
                                                 "extracted) and by publisher, into WebScraping/coverage/")
    reach.add_argument("--output", "-o", default=os.path.join("WebScraping", "coverage"),
                       help="Folder of the tables and the report (default: WebScraping/coverage)")
    reach.add_argument("--verbose", "-v", action="store_true", help="Enable debug-level logging")
    return parser.parse_args(argv)


def run_web(args: argparse.Namespace) -> int:
    """The stages of WebScraping/harvest.py, from the one asked for. Imported here so that the
    window and --help never load them."""
    from .about import starter_job
    from .doctor import check
    from .harvest import Harvest
    from .http import PoliteClient
    from .job import load_job

    args.job = starter_job(args.job)  # a fresh folder: the shipped job files (sse.yaml, the families, …) made first
    try:
        job = load_job(args.job)
    except (OSError, ValueError) as error:
        logging.error(f"{args.job}: {error}")
        return 2
    if getattr(args, "snowball", False):
        job.search.snowball = True
    if args.check:
        return check(job, PoliteClient(job.email()), args.probe_doi or "", os.path.join(args.output, "papers.csv"))
    try:
        with runcontrol.ctrl_c_stops("Web scraping") as control:
            harvest = Harvest(job, args.output)
            if getattr(args, "update", False):
                _since_last_search(job, harvest.ledger.last_search())
            code = _run_stages(args, job, harvest, control)
        if control.is_set():
            print(f"\n{runcontrol.STOPPED_BY_CTRL_C}")
            return 130
        return code
    except UnreadableTable as error:  # nothing was written over: say which file, and how to go on
        logging.error(str(error))
        return 1


def _run_stages(args: argparse.Namespace, job, harvest, control) -> int:
    """The stages asked for, stopped by `control` (Ctrl-C)."""
    if getattr(args, "rescreen", False):
        harvest.rescreen()
    if args.dois is not None:  # search with DOIs: the list as candidates, then download and extract
        from WebScraping.Fetch_DOIs.get_dois import OUTPUT
        listed = args.dois or job.search.doi_list or str(OUTPUT)  # the job's own list, not another job's
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
    if args.command == "coverage":
        return _coverage(args)
    if args.command == "update":
        return _update_all(args)
    # A job or DOI list named on the command line (never the default job): found before the move into the home folder.
    if args.job != DEFAULT_JOB:
        args.job = found_here(args.job)
    args.dois = found_here(args.dois)
    enter_project_home("web", "dois")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    print_banner(f"{FULL_NAME} · Web scraping", DESCRIPTION)
    load_env()  # ELSEVIER_API_KEY, MME_EMAIL, ... from ~/MoukhlijMatExtract/.env

    if args.command == "gui":  # without --output, the window follows the job chosen in it
        from LocalExtraction.about import require_tk
        require_tk("mme-web gui")
        from WebScraping.webgui import main as gui_main  # the same window as `python -m WebScraping gui`
        gui_main(job_path=args.job, output_dir=args.output, workers=args.workers)
        return 0

    from .about import starter_job
    args.job = starter_job(args.job)  # a shipped job not made yet (a fresh folder): made first, so its folder is known
    if args.output is None:  # the job's own database (about.output_for)
        args.output = output_of(args.job)
        logging.info(f"Results folder of this job: {args.output}")
    if not args.check and not rebuild_if_asked(args.output, args.rebuild):
        return 1
    return run_web(args)


def _since_last_search(job, last: Optional[str]) -> None:
    """--update: the job's years narrowed to those since its last search (within the years the job asks for)."""
    from datetime import date
    if not last:
        logging.info("Update: this job was never searched — it is searched in full.")
        return
    low, high = job.search.years or (int(last[:4]), date.today().year)
    job.search.years = (max(low, int(last[:4])), high)
    logging.info(f"Update: last searched on {last} — only the papers published {job.search.years[0]}–"
                 f"{job.search.years[1]} are asked for (what is already in the ledger is not taken twice).")


def _update_all(args: argparse.Namespace) -> int:
    """mme-web update: `run --update` for every job file whose ledger exists, one after the other."""
    from glob import glob

    from .job import load_job
    enter_project_home("web", "dois")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    print_banner(f"{FULL_NAME} · Update", DESCRIPTION)
    load_env()
    worst = 0
    for path in sorted(glob(os.path.join("configs", "*.yaml"))):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            folder = load_job(path).fetch.folder
        except (OSError, ValueError) as error:
            print(f"  {name}: cannot be read — {error}")
            continue
        never_run = not os.path.exists(os.path.join(folder, "ledger.sqlite"))
        if never_run and not args.all:
            print(f"  {name}: never run — left alone (--all runs it too)")
            continue
        print(f"\n=== {name}{' (first run: searched in full)' if never_run else ''} ===")
        run = parse_args(["run", "--job", path, *([] if never_run else ["--update"]), "--workers", str(args.workers),
                          *(["--yes"] if args.yes else []), *(["--verbose"] if args.verbose else [])])
        run.output = output_of(path)
        code = run_web(run)
        if code == 130:  # Ctrl-C: the rest is left for the next update
            return code
        worst = max(worst, code)
    return worst


def _coverage(args: argparse.Namespace) -> int:
    """mme-web coverage: the coverage of every job file of the main folder (coverage.py)."""
    from . import coverage
    output = args.output  # relative: inside the main folder, as every result
    enter_project_home("web")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    print_banner(f"{FULL_NAME} · Coverage", DESCRIPTION)
    folder = coverage.write(output)
    for row in coverage.by_family():
        if row["found"]:
            rate = "—" if row["download_rate"] is None else f"{100 * row['download_rate']:.0f} %"
            print(f"  {row['job']}: {row['found']} found, {row['proposed']} proposed, {row['downloaded']} downloaded "
                  f"({rate}), {row['activation_energies']} activation energies")
    print(f"Coverage written to {os.path.abspath(folder)} (coverage.md, coverage_by_family.csv, "
          "coverage_by_publisher.csv)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
