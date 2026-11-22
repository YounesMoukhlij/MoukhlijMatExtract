# Release/release.py
"""The dataset, ready to deposit (Zenodo, Figshare, a journal's data repository).

It gathers the databases of parts 1 and 2, the ranking and the classification, with:
  - every value and every bibliographic field of every paper — facts and metadata may be shared;
  - the text copied from a paper (sentences, captions, table contents) only where the paper's license
    lets anyone share it (CC BY, CC0, public domain); elsewhere the cell says why it is withheld and
    where to read it;
  - the data dictionary, the run manifests (how each result was made), requirements.lock;
  - a datasheet (README.md: what the data is, how it was collected and processed, its limits);
  - SHA256SUMS of every file, and the whole as one .zip."""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

# Licenses that let anyone copy and adapt the text, commercially too, with attribution only.
SHAREABLE = re.compile(r"^(?:cc[- ]?by(?:[- ]?\d(?:\.\d)?)?|cc0|public[- ]domain|pd)$", re.IGNORECASE)
# Columns that copy a paper's own words; the others hold facts, numbers and bibliographic data.
TEXT_COLUMNS = ("sentence", "context_sentence", "evidence_sentence", "caption", "rows", "headers",
                "transport_component_evidence", "data_origin_evidence")
DATABASE_FILES = ("data_dictionary.csv", "run_manifest.json")


def release_name(folder: Path) -> str:
    """The folder's name in the release: ranking/ and classification/ say more than results/."""
    folder = Path(folder)
    if folder.parent.name == "SelectingTopMaterial":
        return "ranking"
    if folder.name == "Classification":
        return "classification"
    return folder.name


def shareable(license_text: str) -> bool:
    return bool(SHAREABLE.match((license_text or "").strip()))


@dataclass
class Report:
    folder: Path
    archive: Path
    files: int = 0
    papers: int = 0
    excluded: Counter = field(default_factory=Counter)   # papers left out, by why
    regenerated: List[str] = field(default_factory=list)  # results made again from the released databases
    papers_with_text: int = 0
    cells_withheld: int = 0
    licenses: Counter = field(default_factory=Counter)
    tables: Dict[str, int] = field(default_factory=dict)


# How a paper's copy was obtained, as far as a record shows it. A copy with no record ("a file of this
# computer", or put into the folder by hand and taken up as "already in the folder") cannot be shown to be
# a legal one; a copy the log of the earlier downloader says came from a shadow library is not.
_UNRECORDED = {"", "NONE", "a file of this computer", "already in the folder"}
_SHADOW = re.compile(r"sci-?hub|sci-?net|libgen|library\s*genesis|z-?library|anna.?s\s*archive", re.IGNORECASE)


def earlier_downloads(log: Optional[Path]) -> Dict[str, str]:
    """doi -> where the earlier downloader (its log, WebScraping/papers/scrape_log.csv) saved it from."""
    if not log or not Path(log).exists():
        return {}
    try:
        table = pd.read_csv(log, dtype=str, keep_default_na=False, on_bad_lines="skip", encoding="utf-8-sig")
    except (OSError, ValueError, pd.errors.ParserError):
        return {}
    if not {"doi", "result", "source"} <= set(table.columns):
        return {}
    saved = table[table["result"].str.strip().str.lower() == "saved"]
    return {doi.strip().lower(): source.strip() for doi, source in zip(saved["doi"], saved["source"]) if doi.strip()}


def origins_of(databases: Sequence[Path], log: Optional[Path] = None) -> Dict[str, Tuple[bool, str]]:
    """paper_id -> (whether it may be released, how its copy was obtained). Released: a copy a legal source
    gave (recorded with it, or in the earlier downloader's log), or one of the authors' own PDFs (part 1).
    Not released: a copy from a shadow library, or a downloaded copy with no record of where it came from."""
    earlier = earlier_downloads(log)
    found: Dict[str, Tuple[bool, str]] = {}
    for folder in databases:
        path = Path(folder) / "papers.csv"
        if not path.exists():
            continue
        own = "local" in Path(folder).name.lower()  # LocalExtraction: PDFs the authors put there themselves
        papers = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        for row in papers.itertuples(index=False):
            service = str(getattr(row, "source_service", "") or "").strip()
            log_source = earlier.get(str(getattr(row, "doi", "") or "").strip().lower(), "")
            # The source recorded with the copy extracted comes first: a paper an earlier tool took from a
            # shadow library, then downloaded again from a legal source, is the legal copy.
            if service not in _UNRECORDED and not _SHADOW.search(service):
                origin = (True, f"downloaded from {service}")
            elif log_source and _SHADOW.search(log_source):
                origin = (False, f"a copy from a shadow library ({log_source})")
            elif service not in _UNRECORDED:
                origin = (False, f"a copy from a shadow library ({service})")
            elif log_source:
                origin = (True, f"downloaded from {log_source} (by an earlier version)")
            elif own:
                origin = (True, "the authors' own copy")
            else:
                origin = (False, "no record of where the copy came from")
            found.setdefault(row.paper_id, origin)
    return found


def licenses_of(databases: Sequence[Path]) -> Dict[str, Tuple[str, str]]:
    """paper_id -> (license, title), from the papers.csv of each database (the first one wins)."""
    known: Dict[str, Tuple[str, str]] = {}
    for folder in databases:
        path = Path(folder) / "papers.csv"
        if not path.exists():
            continue
        papers = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        for row in papers.itertuples(index=False):
            known.setdefault(row.paper_id, (getattr(row, "license", "") or "not stated", getattr(row, "title", "")))
    return known


def _withheld(license_text: str, page: str) -> str:
    where = f", page {page}" if page and page not in ("NONE", "") else ""
    return (f"withheld: the paper's license ({license_text or 'not stated'}) does not let this text be shared; "
            f"read it in the paper{where}")


def redact(table: pd.DataFrame, licenses: Dict[str, Tuple[str, str]]) -> Tuple[pd.DataFrame, int]:
    """The table with the copied text of papers whose license does not let it be shared replaced by why
    (and where to read it). Returns the table and how many cells were withheld."""
    columns = [c for c in TEXT_COLUMNS if c in table.columns]
    if not columns or "paper_id" not in table.columns:
        return table, 0
    table = table.copy()
    license_of = table["paper_id"].map(lambda p: licenses.get(p, ("not stated", ""))[0])
    closed = ~license_of.map(shareable).astype(bool)  # (an empty table would leave it as objects)
    pages = table["page"] if "page" in table.columns else pd.Series([""] * len(table), index=table.index)
    count = 0
    for column in columns:
        mask = (closed & ~table[column].isin(["", "NONE"])).astype(bool)
        count += int(mask.sum())
        table.loc[mask, column] = [_withheld(lic, page) for lic, page in zip(license_of[mask], pages[mask])]
    return table, count


def _copy_tree(source: Path, target: Path, licenses, report: Report, keep_text: bool,
               excluded: Optional[set] = None) -> None:
    """The CSV files of a results folder (and its sub-folders: the classes, the components), redacted;
    its data dictionary and run manifest as they are. Earlier databases (previous_<date>/) are left out."""
    for path in sorted(source.rglob("*")):
        inside = path.relative_to(source)
        if not path.is_file() or any(part.startswith((".", "previous_")) for part in inside.parts):
            continue
        out = target / inside
        if path.suffix == ".csv" and path.name != "data_dictionary.csv":
            table = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
            if excluded and "paper_id" in table.columns:
                table = table[~table["paper_id"].isin(excluded)]
            if not keep_text:
                table, withheld = redact(table, licenses)
                report.cells_withheld += withheld
            out.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(out, index=False, encoding="utf-8-sig")
            report.tables[str(target.name / inside)] = len(table)
        elif path.name in DATABASE_FILES or path.suffix in (".json", ".html", ".md", ".toml") and path.name != "database.json":
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
        else:
            continue  # database.json and database.xlsx repeat the CSV files, with every text unredacted
        report.files += 1


def _sha256sums(folder: Path) -> Path:
    from LocalExtraction.provenance import file_digest
    lines = [f"{file_digest(p)}  {p.relative_to(folder).as_posix()}"
             for p in sorted(folder.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"]
    path = folder / "SHA256SUMS"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _runs(folder: Path) -> List[dict]:
    try:
        return json.loads((folder / "run_manifest.json").read_text(encoding="utf-8")).get("runs", [])
    except (OSError, ValueError):
        return []


def _years(databases: Sequence[Path]) -> str:
    years = []
    for folder in databases:
        try:
            papers = pd.read_csv(Path(folder) / "papers.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
        except OSError:
            continue
        years += [int(y) for y in papers.get("publication_year", []) if str(y).isdigit()]
    return f"{min(years)}–{max(years)}" if years else "not known"


def collection(job: Optional[Path]) -> str:
    """How the papers were found, from the job file of Web scraping (its search settings)."""
    try:
        import yaml
        search = (yaml.safe_load(Path(job).read_text(encoding="utf-8")) or {}).get("search", {})
    except Exception:
        return "TO COMPLETE — the search: keywords, DOI lists, sources, years. "
    years = search.get("years") or []
    span = f"published {years[0]}–{years[1]}" if len(years) == 2 else "of any year"
    sources = ", ".join(search.get("sources") or []) or "the default sources"
    doi_list = f", and the DOIs of `{search['doi_list']}`" if search.get("doi_list") else ""
    return (f"Web scraping searched {len(search.get('queries') or [])} keyword queries{doi_list} ({span}; at most "
            f"{search.get('max_per_query', '?')} results per query and source) in: {sources}. Each paper found "
            f"was scored on its title and abstract, and those on topic with a legal open copy were proposed for "
            f"download. The search settings are those of the job file `{Path(job).name}`. ")


def datasheet(report: Report, databases: Sequence[Path], extras: Sequence[Path], version: str,
              keep_text: bool, job: Optional[Path] = None) -> str:
    """README.md of the release, after "Datasheets for Datasets" (Gebru et al., 2021). The parts only
    the authors can answer are marked TO COMPLETE."""
    runs = [r for folder in databases for r in _runs(folder)]
    extraction = [r for r in runs if r.get("part") == "extraction"]
    environments = Counter(r["environment"].get("software", "") + " · " + r["environment"].get("language_model", "")
                           for r in extraction if "environment" in r)
    licenses = ", ".join(f"{name}: {n}" for name, n in report.licenses.most_common())
    main = {name: rows for name, rows in report.tables.items() if name.count("/") == 1}
    tables = "\n".join(f"| `{name}` | {rows} |" for name, rows in sorted(main.items()))
    if len(main) < len(report.tables):
        tables += f"\n| … and {len(report.tables) - len(main)} tables in sub-folders (one per class or component) | |"
    text_policy = (
        "Every text cell is as extracted (`--keep-text`): check the licenses before sharing this copy."
        if keep_text else
        f"Values, units, conditions and bibliographic data are given for every paper. Text copied from a "
        f"paper (sentences, captions, table contents) is given only for the {report.papers_with_text} papers "
        f"whose license lets anyone share it (CC BY, CC0, public domain); in the other "
        f"{report.cells_withheld} cells it is replaced by the reason and the page to read it on.")
    left_out = sum(report.excluded.values())
    copies = (
        f"Only papers whose copy was obtained legally are included: downloaded from a legal source (its record "
        f"kept with the paper), or the authors' own copies. {left_out} paper(s) were left out — "
        + "; ".join(f"{why}: {n}" for why, n in report.excluded.most_common())
        + " — and are listed, by DOI only, in `excluded.csv`."
        + (" The ranking and the classification were made again from the released databases (default settings), "
           "so that no paper left out counts in them." if report.regenerated else "")
        if left_out else
        "Every paper's copy was obtained legally: downloaded from a legal source (its record kept with the paper), "
        "or the authors' own copy.")
    # Built before the template: Python 3.11 cannot nest these quotes inside it.
    own, web = "the authors' own PDFs", "papers found and downloaded by Web scraping"
    folders = "\n".join(f"| `{Path(d).name}/` | the database extracted from the papers "
                        f"({own if 'local' in Path(d).name else web}) |" for d in databases)
    results = "\n".join(f"| `{release_name(e)}/` | " + (
        "the ranking by activation energy, per transport component" if release_name(e) == "ranking"
        else "the classification by crystal-structure type and structure family") + " |" for e in extras)
    runs = "\n".join(f"- {n} extraction run(s) with {name}" for name, n in environments.most_common()) \
        or "- see run_manifest.json"
    return f"""# MoukhlijMatExtract dataset — {datetime.now(timezone.utc):%Y-%m-%d}

Activation energies, ionic and electronic conductivities and diffusion coefficients of solid-state
electrolytes, extracted from {report.papers} scientific papers by MoukhlijMatExtract {version}, with the
material, the conditions and the provenance of every value; the materials ranked by activation energy
and classified by crystal-structure type and structure family.

## Contents

| Folder | What it holds |
|---|---|
{folders}
{results}

Every column of every table is described in `data_dictionary.csv` (in each database folder). How each
file was made — settings, software and language-model versions, inputs, row counts, SHA-256 — is in each
folder's `run_manifest.json`; the exact Python environment, in `requirements.lock`. `SHA256SUMS` lists a
checksum of every file of this release.

| Table | Rows |
|---|---:|
{tables}

## Composition

- Papers: {report.papers}, published {_years(databases)}.
- Licenses of the papers' copies: {licenses}.
- {copies}
- {text_policy}
- Each value states where it was read (text, table, figure caption; page), its material and how it was tied
  to it, its temperature, pressure, origin (experimental / simulation), transport component and moving
  species, each with its `basis`: stated by the paper, read from the context, or assumed (and why).
- `plausibility` flags values outside the range known for ion conductors or carried by another species;
  the ranking leaves them out.

## Collection

{collection(job)}Only legal open-access copies were downloaded, following each site's robots.txt.
TO COMPLETE — the dates of the searches, and how the papers proposed were reviewed.

## Processing

{runs}
- Extraction is rule-based (patterns, a spaCy parse, a chemistry engine); see the software's documentation.

## Accuracy

TO COMPLETE — the precision, recall and F1 measured with `mme-eval` on the annotated sample
(`Evaluation/scores/report.md`), with their 95 % intervals and the inter-annotator agreement.

## Uses and limits

- Values are as the papers report them; an assumed condition is marked so in `basis` and counted in
  `n_assumed` — filter on these before drawing conclusions from a condition.
- `confidence` is a heuristic score, not a probability.
- TO COMPLETE — uses the dataset is not suited for.

## License and citation

TO COMPLETE — the license of this dataset (CC BY 4.0 is usual for data; the text cells of CC BY papers keep
their own attribution: `paper_id`, `doi`, `title`). Cite the dataset's DOI and the software:
MoukhlijMatExtract {version}, https://github.com/YounesMoukhlij/MoukhlijMatExtract.
"""


def installed_packages() -> str:
    """The Python packages installed where the release is made, pinned ("name==version"), as `pip freeze`
    writes them: the environment the results can be reproduced in."""
    from importlib.metadata import distributions
    import platform
    import sys
    pinned = sorted({f"{d.metadata['Name']}=={d.version}" for d in distributions() if d.metadata["Name"]},
                    key=str.casefold)
    return (f"# The packages installed when this release was made (Python {platform.python_version()}, "
            f"{sys.platform}).\n# pip install -r requirements.lock\n" + "\n".join(pinned) + "\n")


def make(databases: Sequence[Path], extras: Sequence[Path], out_root: Path, version: str,
         keep_text: bool = False, lock: Optional[Path] = None, job: Optional[Path] = None,
         log: Optional[Path] = None, keep_unrecorded: bool = False) -> Report:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"MoukhlijMatExtract-dataset-{version or 'dev'}-{stamp}"
    folder = Path(out_root) / name
    folder.mkdir(parents=True)
    report = Report(folder=folder, archive=archive_of(folder))
    origins = origins_of(databases, log)
    excluded = set() if keep_unrecorded else {pid for pid, (ok, _) in origins.items() if not ok}
    report.excluded = Counter(why for pid, (ok, why) in origins.items() if pid in excluded)
    licenses = {pid: about for pid, about in licenses_of(databases).items() if pid not in excluded}
    report.papers = len(licenses)
    report.licenses = Counter(lic for lic, _ in licenses.values())
    report.papers_with_text = sum(shareable(lic) for lic, _ in licenses.values())
    for source in databases:
        _copy_tree(Path(source), folder / release_name(source), licenses, report, keep_text, excluded)
    if excluded:
        # The ranking and the classification weigh every paper together: made again from the released
        # databases, so that no paper left out counts in them.
        _regenerate(extras, [folder / release_name(d) for d in databases], folder, licenses, report, keep_text)
        listed = [{"paper_id": pid, "doi": doi, "why": origins[pid][1]} for pid, doi in _dois(databases).items()
                  if pid in excluded]
        pd.DataFrame(listed, columns=["paper_id", "doi", "why"]).to_csv(folder / "excluded.csv", index=False,
                                                                       encoding="utf-8-sig")
        report.files += 1
    else:
        for source in extras:
            _copy_tree(Path(source), folder / release_name(source), licenses, report, keep_text)
    if lock and Path(lock).exists():
        shutil.copy2(lock, folder / "requirements.lock")
    else:  # installed with pip, without the project folder: the environment as it is, package by package
        (folder / "requirements.lock").write_text(installed_packages(), encoding="utf-8")
    report.files += 1
    (folder / "README.md").write_text(datasheet(report, databases, extras, version, keep_text, job), encoding="utf-8")
    seal(folder)
    return report


def _dois(databases: Sequence[Path]) -> Dict[str, str]:
    known: Dict[str, str] = {}
    for folder in databases:
        path = Path(folder) / "papers.csv"
        if path.exists():
            papers = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
            for row in papers.itertuples(index=False):
                known.setdefault(row.paper_id, str(getattr(row, "doi", "") or ""))
    return known


def _regenerate(extras: Sequence[Path], released: Sequence[Path], folder: Path, licenses, report: Report,
                keep_text: bool) -> None:
    """The ranking and the classification made again, with their default settings, from the released
    databases (into a scratch folder first, then copied in like any result folder)."""
    import contextlib
    import io
    import tempfile
    wanted = {release_name(Path(e)) for e in extras}
    sources = [str(d) for d in released if (d / "papers.csv").exists()]
    if not wanted or not sources:
        return
    with tempfile.TemporaryDirectory(prefix="mme-release-") as scratch:
        for kind in ("ranking", "classification"):
            if kind not in wanted:
                continue
            out = Path(scratch) / kind
            here = os.getcwd()
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    if kind == "ranking":
                        from SelectingTopMaterial.cli import main as rank
                        rank(["--source", *sources, "--out", str(out), "--force", "--quiet", "--no-color"])
                    else:
                        from Classification.cli import main as classify
                        classify(["--source", *sources, "--out", str(out), "--force"])
            finally:
                os.chdir(here)  # each command works from the project home
            if out.is_dir():
                _copy_tree(out, folder / kind, licenses, report, keep_text)
                report.regenerated.append(kind)


def archive_of(folder: Path) -> Path:
    """<folder>.zip — not with_suffix: "dataset-1.0.3-…" would lose ".3-…" as if it were an extension."""
    return folder.parent / f"{folder.name}.zip"


def seal(folder: Path) -> Path:
    """SHA256SUMS and the .zip of a release folder — again after its README was completed by hand."""
    folder = Path(folder)
    _sha256sums(folder)
    archive_path = archive_of(folder)
    temporary = archive_path.with_name(archive_path.name + ".part")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, Path(folder.name) / path.relative_to(folder))
    temporary.replace(archive_path)
    return archive_path


def unfinished(folder: Path) -> int:
    """How many parts of the README are still marked TO COMPLETE."""
    try:
        return (Path(folder) / "README.md").read_text(encoding="utf-8").count("TO COMPLETE")
    except OSError:
        return 0
