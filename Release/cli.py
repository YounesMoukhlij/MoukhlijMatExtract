# Release/cli.py
"""mme-release (python -m Release): the dataset, ready to deposit — see release.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from LocalExtraction.about import PROJECT_HOME, command_name, enter_project_home, version, version_text

NAME = "Release"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASES = (PROJECT_HOME / "LocalExtraction" / "local_output", PROJECT_HOME / "WebScraping" / "web_output")
DEFAULT_EXTRAS = (PROJECT_HOME / "SelectingTopMaterial" / "results", PROJECT_HOME / "Classification")
DEFAULT_OUT = PROJECT_HOME / "Release"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=command_name("mme-release", NAME),
        description="Gathers the databases, the ranking and the classification into one folder and one .zip, "
                    "ready to deposit (Zenodo, Figshare, a journal): every value and bibliographic field; the text "
                    "copied from a paper only where its license lets anyone share it (CC BY, CC0, public domain); "
                    "the data dictionary, the run manifests, requirements.lock, a datasheet (README.md, with the "
                    "parts only you can write marked TO COMPLETE) and SHA256SUMS.",
        epilog="Nothing of the databases is changed. MoukhlijMatExtract (MME) — Created by Younes Moukhlij.")
    parser.add_argument("--source", "-s", nargs="+", action="extend", metavar="DIR",
                        help="Database folder(s) to release (default: LocalExtraction/local_output and "
                             "WebScraping/web_output, whichever exist)")
    parser.add_argument("--with", dest="extras", nargs="+", action="extend", metavar="DIR",
                        help="Other result folders to add (default: SelectingTopMaterial/results and Classification, "
                             "whichever exist)")
    parser.add_argument("--no-results", action="store_true", help="Release the databases only")
    parser.add_argument("--out", "-o", type=Path, default=DEFAULT_OUT, metavar="DIR",
                        help="Folder the release is written into (default: Release/)")
    parser.add_argument("--keep-text", action="store_true",
                        help="Keep the text of every paper, whatever its license (for sharing with your co-authors, "
                             "not for a public deposit)")
    parser.add_argument("--keep-unrecorded", action="store_true",
                        help="Keep the papers with no record of a legal copy (a copy from a shadow library, or a "
                             "downloaded PDF whose source was not recorded) — for your own use only, never a public "
                             "deposit. By default they are left out, and listed in excluded.csv")
    parser.add_argument("--finish", type=Path, metavar="FOLDER",
                        help="After completing the README of a release folder: write its SHA256SUMS and .zip again")
    parser.add_argument("--version", action="version", version=version_text("mme-release"))
    return parser


def _main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    enter_project_home()
    if args.finish:
        from .release import seal, unfinished
        folder = args.finish.expanduser()
        if not (folder / "README.md").exists():
            print(f"{folder} is not a release folder (no README.md).", file=sys.stderr)
            return 1
        archive = seal(folder)
        left = unfinished(folder)
        print(f"Wrote {folder / 'SHA256SUMS'} and {archive}"
              + (f"\n  README.md still has {left} part(s) marked TO COMPLETE." if left else ""))
        return 0
    databases = [Path(s).expanduser() for s in args.source] if args.source else list(DEFAULT_DATABASES)
    for left_out in [d for d in databases if d.is_dir() and not (d / "papers.csv").exists()]:
        why = ("its rebuild is not finished: run that part again first" if (left_out / "rebuild_pending.json").exists()
               else "it holds no papers.csv")
        print(f"Left out {left_out}: {why}.", file=sys.stderr)
    databases = [d for d in databases if (d / "papers.csv").exists()]
    for partial in [d for d in databases if (d / "rebuild_pending.json").exists()]:
        print(f"Warning: {partial} is only partly rebuilt (a run was stopped): run that part again to finish it "
              "before a release you deposit.", file=sys.stderr)
    if not databases:
        print("There is no database to release: extract papers first (mme-local or mme-web).", file=sys.stderr)
        return 1
    extras = [] if args.no_results else (
        [Path(e).expanduser() for e in args.extras] if args.extras else list(DEFAULT_EXTRAS))
    extras = [e for e in extras if e.is_dir() and any(e.rglob("*.csv"))]

    from LocalExtraction.provenance import Run
    from .release import make
    run = Run("release", args.out.expanduser(), settings={"databases": [str(d) for d in databases],
                                                          "with": [str(e) for e in extras], "keep_text": args.keep_text,
                                                          "keep_unrecorded": args.keep_unrecorded})
    report = make(databases, extras, args.out.expanduser(), version(), keep_text=args.keep_text,
                  lock=ROOT / "requirements.lock", job=PROJECT_HOME / "configs" / "sse.yaml",
                  log=PROJECT_HOME / "WebScraping" / "papers" / "scrape_log.csv", keep_unrecorded=args.keep_unrecorded)
    run.finish({"papers": report.papers, "files": report.files, "cells_withheld": report.cells_withheld},
               files=[report.archive.name])
    print(f"Wrote {report.folder}\n  and {report.archive} ({report.archive.stat().st_size / 1e6:.1f} MB)\n"
          f"  {report.papers} papers, {report.files} files; the text of {report.papers_with_text} openly licensed "
          f"papers kept, {report.cells_withheld} text cells of the others withheld (values kept for every paper).\n"
          + (f"  {sum(report.excluded.values())} paper(s) left out — no record of a legal copy: "
             + "; ".join(f"{why}: {n}" for why, n in report.excluded.most_common())
             + f" (listed in excluded.csv{'; ranking and classification made again without them' if report.regenerated else ''}).\n"
             if report.excluded else "")
          + f"  Next: complete the parts of README.md marked TO COMPLETE, then "
          f"{command_name('mme-release', NAME)} --finish {report.folder} — and upload the .zip.")
    return 0




def main(argv: Optional[Sequence[str]] = None) -> int:
    """The command. Stopped from the terminal (Ctrl-C, kill, the terminal closed), it finishes and saves first, saying
    so in a box; a second signal quits at once. The window (`gui`) has its own Stop."""
    import sys as _sys
    from LocalExtraction import runcontrol
    words = list(_sys.argv[1:] if argv is None else argv)
    if words[:1] == ["gui"]:
        return _main(argv)
    with runcontrol.finish_then_stop("Release"):
        return _main(argv)


if __name__ == "__main__":
    sys.exit(main())
