"""The held-out source of the evaluation (docs/EVALUATION_PROTOCOL.md § 3): a copy of a database without the papers
already used to develop or check the extraction rules, so that the draw measures the tool on papers it was never
tuned on. The database itself is only read.

    python scripts/audit/heldout_source.py <database> <copy> <paper list or sample csv> [...]

A list is a text file of paper ids (one per line) or a CSV with a paper_id column. The copy holds every CSV of the
database filtered to the papers kept, and left_out.csv: each paper left out and the list it was found in."""

import csv
import shutil
import sys
from pathlib import Path

import pandas as pd


def used_papers(lists):
    found = {}
    for path in map(Path, lists):
        if path.suffix == ".csv":
            with open(path, encoding="utf-8-sig", newline="") as f:
                ids = [row["paper_id"] for row in csv.DictReader(f) if row.get("paper_id")]
        else:
            ids = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for paper in ids:
            found.setdefault(paper, path.name)
    return found


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    database, copy, lists = Path(argv[0]), Path(argv[1]), argv[2:]
    if copy.exists():
        sys.exit(f"{copy} exists already: choose a new folder (the copy is never written over).")
    used = used_papers(lists)
    copy.mkdir(parents=True)
    papers = pd.read_csv(database / "papers.csv", dtype=str, keep_default_na=False)
    left = papers[papers["paper_id"].isin(used) | papers["filename"].isin(used)]
    keep = set(papers["paper_id"]) - set(left["paper_id"])
    for table in database.glob("*.csv"):
        frame = pd.read_csv(table, dtype=str, keep_default_na=False)
        if "paper_id" in frame.columns:
            frame = frame[frame["paper_id"].isin(keep)]
        frame.to_csv(copy / table.name, index=False, encoding="utf-8-sig")
    for name in ("run_manifest.json",):
        if (database / name).exists():
            shutil.copy(database / name, copy / name)
    pd.DataFrame({"paper_id": left["paper_id"],
                  "found_in": [used.get(p) or used.get(f) for p, f in zip(left["paper_id"], left["filename"])]}
                 ).to_csv(copy / "left_out.csv", index=False)
    print(f"{len(keep):,} papers kept, {len(left):,} left out (listed in {copy / 'left_out.csv'}).")


if __name__ == "__main__":
    main(sys.argv[1:])
