# Evaluation/reference.py
"""MoukhlijMatExtract against curated databases of solid electrolytes.

A curated database was built by people reading papers: for the papers it covers, it says which materials
and conductivities a careful reader finds. The comparison runs MoukhlijMatExtract on those same papers —
their legal open copies, fetched into a folder of their own so the user's databases stay as they are —
and asks, for every curated entry of a paper it could read: did it find that material, that value?

    recall of the material         the composition is among the paper's extracted ionic conductivities
    recall of the record           … with the curated value (within 0.1 decade, and within 2 %)
    value agreement                how far the extracted values of the matched entries are from the curated ones

Precision is not measured here: a curated database is not exhaustive (it keeps one value per material,
room temperature only, …), so a value it lacks is not wrong. Precision comes from mme-eval score.

The databases, downloaded at run time from their publishers (never shipped with MoukhlijMatExtract):
  OBELiX     Therrien et al., arXiv:2502.14234 (2025) — CC BY 4.0 — github.com/NRC-Mila/OBELiX
  Liverpool  Hargreaves et al., npj Comput. Mater. 2023 — academic use with citation; commercial use
             only under licence from the University of Liverpool."""

from __future__ import annotations

import io
import json
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

import pandas as pd

from .compare import max_matching, same_material

# A curated database: where it is published, how to cite it, and how to read it into one shape.
DATABASES = {
    "obelix": {
        "name": "OBELiX",
        "files": {"raw.xlsx": "https://raw.githubusercontent.com/NRC-Mila/OBELiX/main/data/raw.xlsx"},
        "citation": "F. Therrien et al., OBELiX: A Curated Dataset of Crystal Structures and Experimentally Measured "
                    "Ionic Conductivities for Lithium Solid-State Electrolytes, arXiv:2502.14234 (2025); "
                    "github.com/NRC-Mila/OBELiX",
        "license": "CC BY 4.0",
        "temperature": "room temperature",
    },
    "liverpool": {
        "name": "Liverpool Ionics Dataset",
        "files": {"LiIonDatabase.csv": "https://pcwww.liv.ac.uk/~msd30/lmds/LiIonDatabase.csv"},
        "citation": "C. J. Hargreaves et al., A database of experimentally measured lithium solid electrolyte "
                    "conductivities evaluated with machine learning, npj Comput. Mater. 9, 9 (2023), "
                    "doi:10.1038/s41524-022-00951-z; "
                    "pcwww.liv.ac.uk/~msd30/lmds/LiIonDatabase.html",
        "license": "University of Liverpool: academic use with citation; commercial use only under licence",
        "temperature": "as listed",
    },
}
COLUMNS = ["reference", "ref_id", "doi", "composition", "conductivity_S_cm", "temperature_K"]
LOOSE = 0.1      # decades: a value read off a plot, or rounded, by the curators or the paper
STRICT = 0.0086  # decades: 2 %
ROOM = (288.0, 308.0)


def _doi(text) -> str:
    """One DOI, or several joined by "|" when an entry gives several ("10.1/a|10.1/b")."""
    found = []
    for part in re.split(r"[|;,\s]+(?=(?:https?://|doi:|10\.))", str(text or "").strip().lower()):
        part = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", part.strip())
        if part.startswith("10."):
            found.append(part)
    return "|".join(dict.fromkeys(found))


def dois_of(text: str):
    return [d for d in str(text or "").split("|") if d]


def _float(text) -> Optional[float]:
    try:
        number = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def download(name: str, folder: Path, refresh: bool = False, get: Optional[Callable[[str], bytes]] = None) -> Path:
    """The files of a curated database, in folder/<name>/ (kept: downloaded again only with refresh)."""
    target = Path(folder) / name
    target.mkdir(parents=True, exist_ok=True)
    for filename, url in DATABASES[name]["files"].items():
        path = target / filename
        if path.exists() and not refresh:
            continue
        if get is None:
            import requests
            from WebScraping.averageScrap.http import PRODUCT, VERSION
            try:
                response = requests.get(url, timeout=60, headers={"User-Agent": f"{PRODUCT}/{VERSION}"})
            except requests.exceptions.SSLError as error:
                # The certificate is not checked away: the user downloads the file with a browser instead.
                raise RuntimeError(f"its server's certificate could not be verified ({error.__class__.__name__}). "
                                   f"Download {url} with a browser and save it as {path}, then run again") from error
            response.raise_for_status()
            data = response.content
        else:
            data = get(url)
        part = path.with_name(path.name + ".part")
        part.write_bytes(data)
        part.replace(path)
        (target / "SOURCE.txt").write_text(
            f"{DATABASES[name]['name']}\nDownloaded {datetime.now(timezone.utc):%Y-%m-%d} from {url}\n"
            f"License: {DATABASES[name]['license']}\nCite: {DATABASES[name]['citation']}\n", encoding="utf-8")
    return target


def load(name: str, folder: Path) -> pd.DataFrame:
    """The entries of a curated database in one shape: reference, ref_id, doi, composition,
    conductivity_S_cm, temperature_K (None for "room temperature")."""
    folder = Path(folder) / name
    rows = []
    if name == "obelix":
        table = pd.read_excel(folder / "raw.xlsx", dtype=str)
        table.columns = [re.sub(r"\W+", "_", str(c)).strip("_").lower() for c in table.columns]
        table = table.loc[:, ~table.columns.duplicated()]
        for r in table.to_dict("records"):
            rows.append({"reference": "OBELiX", "ref_id": r.get("id", ""), "doi": _doi(r.get("doi")),
                         "composition": r.get("true_composition") or r.get("reduced_composition") or "",
                         "conductivity_S_cm": _float(r.get("ionic_conductivity_s_cm_1")), "temperature_K": None})
        return pd.DataFrame(rows, columns=COLUMNS)
    if name == "liverpool":
        lines = (folder / "LiIonDatabase.csv").read_text(encoding="utf-8-sig").splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("ID,"))  # after the licence text
        table = pd.read_csv(io.StringIO("\n".join(lines[start:])), dtype=str)
        for r in table.itertuples(index=False):
            celsius = _float(r.temperature)
            rows.append({"reference": "Liverpool", "ref_id": r.ID, "doi": _doi(r.source), "composition": r.composition,
                         "conductivity_S_cm": _float(r.target),
                         "temperature_K": None if celsius is None else celsius + 273.15})
        return pd.DataFrame(rows, columns=COLUMNS)
    raise ValueError(f"unknown database {name}")


# ---- the papers, fetched and extracted apart -----------------------------------------------------

def fetch_papers(dois: Sequence[str], papers: Path, limit: Optional[int] = None, stop_event=None) -> Dict[str, int]:
    """The legal open copies of these papers, into `papers` (the downloader and services of Web scraping,
    with the job's sources and contact). A DOI tried before (fetched.json) is not tried again."""
    from WebScraping.averageScrap.about import DEFAULT_JOB
    from WebScraping.averageScrap.fetch import Downloader
    from WebScraping.averageScrap.http import PoliteClient
    from WebScraping.averageScrap.job import load_env, load_job
    from WebScraping.averageScrap.resolve import Resolver
    from WebScraping.averageScrap.sources.openalex import OpenAlex

    papers.mkdir(parents=True, exist_ok=True)
    log_path = papers / "fetched.json"
    tried: Dict[str, dict] = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    todo = [d for d in dict.fromkeys(dois) if d and d not in tried]
    if limit is not None:
        todo = todo[:limit]
    counts = Counter(v["status"] for v in tried.values())
    if not todo:
        return dict(counts)
    load_env()
    job = load_job(str(Path(DEFAULT_JOB)))
    client = PoliteClient(job.email())
    from WebScraping.averageScrap.elsevier import Elsevier
    from WebScraping.averageScrap.wiley import Wiley
    elsevier = Elsevier.from_env() if "elsevier" in job.fetch.sources else None
    wiley = Wiley.from_env() if "wiley" in job.fetch.sources else None
    downloader = Downloader(str(papers), client, Resolver(client, job.fetch.sources, job.email(), elsevier, wiley),
                            job.fetch.max_pdf_mb)
    records = {c.doi.lower(): c for c in OpenAlex(client, job.email()).lookup_many(todo)}
    from WebScraping.averageScrap.ledger import Candidate
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from LocalExtraction import runcontrol

    def one(doi: str):
        candidate = records.get(doi) or Candidate(key=f"doi:{doi}", doi=doi)
        return doi, downloader.fetch(candidate)

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, job.fetch.workers)) as pool:
        futures = [pool.submit(runcontrol.task(stop_event, one, d)) for d in todo]
        for future in as_completed(futures):
            try:
                doi, outcome = future.result()
            except runcontrol.StepStopped:
                break
            tried[doi] = {"status": outcome.status, "service": outcome.service, "license": outcome.license,
                          "file": Path(outcome.file).name if outcome.file else "", "error": outcome.error}
            counts[outcome.status] += 1
            done += 1
            if done % 20 == 0 or done == len(todo):
                logging.info(f"Reference papers: {done} of {len(todo)} looked for "
                             f"({counts['downloaded']} with an open copy so far)")
                log_path.write_text(json.dumps(tried, indent=1), encoding="utf-8")
    log_path.write_text(json.dumps(tried, indent=1), encoding="utf-8")
    return dict(counts)


def extract(papers: Path, output: Path, workers: int = 4, stop_event=None) -> int:
    """Extracts the PDFs of `papers` into `output` with the program as it is (only the new ones)."""
    from LocalExtraction.cli import rebuild_if_asked, run_extraction
    from WebScraping.averageScrap.sidecar import read_provenance
    output.mkdir(parents=True, exist_ok=True)
    from LocalExtraction.exporter import StrictExporter
    # a benchmark measures this version: what an earlier version extracted is extracted again, never added to
    rebuild_if_asked(str(output), StrictExporter.is_outdated(str(output)))
    return run_extraction(str(papers), str(output), max_workers=workers, provenance=read_provenance(str(papers)),
                          origin="web", lookup=True, stop_event=stop_event)


# ---- the comparison ----------------------------------------------------------------------------------

def _temperature_of(text: str) -> Optional[float]:
    """Kelvin, from the temperature column of the extraction ("298.1 K", "room temperature" -> 298)."""
    text = str(text or "").strip().lower()
    if not text or text in ("none", "not stated"):
        return None
    if text.startswith("room"):
        return 298.0
    found = re.match(r"^(-?\d+(?:\.\d+)?)\s*k\b", text)
    return float(found.group(1)) if found else None


def _same_temperature(ref: Optional[float], ours: Optional[float]) -> bool:
    if ref is None or (isinstance(ref, float) and math.isnan(ref)):  # a room-temperature value (NaN: from pandas)
        return ours is None or ROOM[0] <= ours <= ROOM[1]
    if ours is None:
        return ROOM[0] <= ref <= ROOM[1]
    return abs(ref - ours) <= 5.0 or (ROOM[0] <= ref <= ROOM[1] and ROOM[0] <= ours <= ROOM[1])


def _decades(a: float, b: float) -> float:
    return abs(math.log10(a) - math.log10(b)) if a and b and a > 0 and b > 0 else float("inf")


@dataclass
class Comparison:
    reference: str
    entries: int
    papers: int
    papers_read: int
    entries_read: int
    material: int
    record_loose: int
    record_strict: int
    median_decades: Optional[float]
    rows: pd.DataFrame


def compare(reference: pd.DataFrame, output: Path, doi_of_file: Dict[str, str]) -> Comparison:
    """Each curated entry of a paper the extraction read, against the paper's extracted ionic
    conductivities: the most entries matched with material, value and temperature (loose), each
    extracted value used once."""
    papers = pd.read_csv(output / "papers.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig") \
        if (output / "papers.csv").exists() else pd.DataFrame(columns=["paper_id", "doi"])
    values = pd.read_csv(output / "ionic_conductivity.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig") \
        if (output / "ionic_conductivity.csv").exists() else pd.DataFrame()
    doi_of_paper = {}
    for row in papers.itertuples(index=False):
        doi = _doi(row.doi) or doi_of_file.get(row.paper_id, "")
        if doi:
            doi_of_paper[row.paper_id] = doi
    read = set(doi_of_paper.values())
    ours = defaultdict(list)
    for row in values.to_dict("records"):
        doi = doi_of_paper.get(row["paper_id"])
        value = _float(row.get("ionic_conductivity_S_cm"))
        if doi and value:
            ours[doi].append({**row, "_value": value, "_kelvin": _temperature_of(row.get("temperature"))})

    reference = reference[reference["conductivity_S_cm"].notna() & (reference["doi"] != "")]
    reference = reference.assign(paper=[next((d for d in dois_of(x) if d in read), dois_of(x)[0])
                                        for x in reference["doi"]])
    out_rows = []
    material = loose = strict = 0
    gaps = []
    for doi, entries in reference.groupby("paper"):
        if doi not in read:
            for e in entries.to_dict("records"):
                out_rows.append({**e, "paper_read": False, "found": "paper not read"})
            continue
        extracted = ours.get(doi, [])
        entries = entries.to_dict("records")
        fits = lambda e, o: (same_material(o["material_formula"], e["composition"])  # noqa: E731
                             and _decades(o["_value"], e["conductivity_S_cm"]) <= LOOSE
                             and _same_temperature(e["temperature_K"], o["_kelvin"]))
        pairs = dict(max_matching(entries, extracted, fits,
                                  prefer=lambda e, o: -_decades(o["_value"], e["conductivity_S_cm"])))
        for i, e in enumerate(entries):
            same = [o for o in extracted if same_material(o["material_formula"], e["composition"])]
            material += bool(same)
            if i in pairs:
                o = extracted[pairs[i]]
                gap = _decades(o["_value"], e["conductivity_S_cm"])
                gaps.append(gap)
                loose += 1
                strict += gap <= STRICT
                found = "material and value" + (" (within 2 %)" if gap <= STRICT else " (within 0.1 decade)")
                out_rows.append({**e, "paper_read": True, "found": found, "extracted_formula": o["material_formula"],
                                 "extracted_S_cm": o["_value"], "extracted_temperature": o.get("temperature", ""),
                                 "decades_apart": round(gap, 4), "sentence": o.get("sentence", "")})
            elif same:
                closest = min(same, key=lambda o: _decades(o["_value"], e["conductivity_S_cm"]))
                out_rows.append({**e, "paper_read": True, "found": "material, another value",
                                 "extracted_formula": closest["material_formula"], "extracted_S_cm": closest["_value"],
                                 "extracted_temperature": closest.get("temperature", ""),
                                 "decades_apart": round(_decades(closest["_value"], e["conductivity_S_cm"]), 4),
                                 "sentence": closest.get("sentence", "")})
            else:
                out_rows.append({**e, "paper_read": True, "found": "not found"})
    rows = pd.DataFrame(out_rows)
    entries_read = int(rows["paper_read"].sum()) if len(rows) else 0
    gaps.sort()
    return Comparison(reference=str(reference["reference"].iloc[0]) if len(reference) else "", entries=len(reference),
                      papers=reference["paper"].nunique(), papers_read=len(read & set(reference["paper"])),
                      entries_read=entries_read, material=material, record_loose=loose, record_strict=strict,
                      median_decades=gaps[len(gaps) // 2] if gaps else None, rows=rows)


def tool_output(predictions: Path, ours: Path, folder: Path) -> Path:
    """Another tool's values for the same PDFs (a predictions CSV: paper_id — the PDF's file name —,
    property, material, value, unit, and optionally temperature) as a folder compare() reads: its ionic
    conductivities in S/cm, beside the papers MoukhlijMatExtract read — the same papers, so the same
    entries are looked for."""
    import shutil
    from .compare import to_database_unit
    table = pd.read_csv(predictions, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    rows = []
    for row in table.to_dict("records"):
        if row.get("property") != "ionic_conductivity":
            continue
        value, _ = to_database_unit("ionic_conductivity", row.get("value"), row.get("unit", ""))
        if value:
            rows.append({"paper_id": row.get("paper_id", ""), "material_formula": row.get("material", ""),
                         "ionic_conductivity_S_cm": value, "temperature": row.get("temperature") or "NONE"})
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["paper_id", "material_formula", "ionic_conductivity_S_cm", "temperature"]).to_csv(
        folder / "ionic_conductivity.csv", index=False, encoding="utf-8-sig")
    if (ours / "papers.csv").exists():
        shutil.copy2(ours / "papers.csv", folder / "papers.csv")
    return folder


def report(results: Sequence[Comparison], fetched: Dict[str, int], version: str,
           others: Optional[Dict[str, Sequence[Comparison]]] = None) -> str:
    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.1f} %" if d else "–"

    lines = ["# MoukhlijMatExtract against curated databases", "",
             f"MoukhlijMatExtract {version}, {datetime.now(timezone.utc):%Y-%m-%d}. The papers of each curated database "
             "were fetched (legal open copies only) and extracted as any paper; each curated entry of a paper that "
             "could be read is looked for among the paper's extracted ionic conductivities: the same composition, the "
             f"same value (within {LOOSE} decade; within 2 % for the strict count) and a compatible temperature.", "",
             f"Papers looked for: {sum(fetched.values())} — open copy found: {fetched.get('downloaded', 0)}, none: "
             f"{fetched.get('closed', 0)}, failed: {fetched.get('failed', 0)}. Add the others' PDFs by hand "
             "(institutional access) to Evaluation/reference/papers/ to read them too.", "",
             "| Database | Entries | Papers | Papers read | Entries of papers read | Material found | Material and value | "
             "… within 2 % | Median distance (decades) |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        lines.append(f"| {r.reference} | {r.entries} | {r.papers} | {r.papers_read} | {r.entries_read} | "
                     f"{r.material} ({pct(r.material, r.entries_read)}) | {r.record_loose} "
                     f"({pct(r.record_loose, r.entries_read)}) | {r.record_strict} ({pct(r.record_strict, r.entries_read)}) | "
                     f"{'–' if r.median_decades is None else f'{r.median_decades:.3f}'} |")
    lines += ["", "Recall only: a curated database is not exhaustive (one value per material, room temperature …), so "
              "a value it lacks is not an error. Each entry and what was found for it: reference_comparison.csv.", ""]
    if others:
        lines += ["## Other tools on the same papers", "",
                  "The same entries looked for, the same way, among the ionic conductivities each tool gives for the same "
                  "PDFs. A tool that gives no temperature is taken at room temperature.", "",
                  "| Tool | Database | Entries of papers read | Material found | Material and value | … within 2 % |",
                  "|---|---|---:|---:|---:|---:|"]
        for tool, rows in [("MoukhlijMatExtract", results), *others.items()]:
            for r in rows:
                lines.append(f"| {tool} | {r.reference} | {r.entries_read} | {r.material} ({pct(r.material, r.entries_read)}) "
                             f"| {r.record_loose} ({pct(r.record_loose, r.entries_read)}) | {r.record_strict} "
                             f"({pct(r.record_strict, r.entries_read)}) |")
        lines.append("")
    lines += ["## Sources", ""]
    for key, about in DATABASES.items():
        if any(r.reference.lower().startswith(about["name"].split()[0].lower()) for r in results):
            lines.append(f"- **{about['name']}** — {about['citation']}. License: {about['license']}.")
    lines.append("")
    return "\n".join(lines)


def doi_of_files(papers: Path) -> Dict[str, str]:
    """file name -> DOI, from the sidecars the downloader writes next to each PDF."""
    known = {}
    for sidecar in Path(papers).glob("*.json"):
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("doi"):
            known[sidecar.with_suffix(".pdf").name] = _doi(data["doi"])
    return known



# ---- a database of MoukhlijMatExtract against a curated one, material by material --------------------

AGAINST_COLUMNS = ["reference", "composition", "curated_S_cm", "curated_entries", "our_material", "our_S_cm",
                   "our_values", "our_papers", "decades"]


def _room(kelvin: Optional[float]) -> bool:
    return kelvin is None or (isinstance(kelvin, float) and math.isnan(kelvin)) or ROOM[0] <= kelvin <= ROOM[1]


def against(reference: pd.DataFrame, output: Path) -> pd.DataFrame:
    """Each room-temperature material of a curated database, met in a results folder of MoukhlijMatExtract (any
    paper, not only the curated one's): the median of the curated values, the median of ours at room temperature,
    and how far apart they are in decades (log10 ours − log10 curated; empty when the material is not in ours).

    Unlike `compare`, the papers need not be the same: this is how the two databases agree where they overlap, and
    how much of the curated one ours covers."""
    from statistics import median
    from .compare import _composition
    table = pd.read_csv(Path(output) / "ionic_conductivity.csv", dtype=str, keep_default_na=False)
    ours: Dict[str, list] = defaultdict(list)
    for r in table.to_dict("records"):
        value, kelvin = _float(r.get("ionic_conductivity_S_cm")), _temperature_of(r.get("temperature"))
        if value and value > 0 and kelvin is not None and ROOM[0] <= kelvin <= ROOM[1]:  # a stated room temperature
            ours[r.get("material_formula", "")].append((value, r.get("paper_id", "")))
    by_elements: Dict[frozenset, list] = defaultdict(list)  # compared only with the materials of the same elements
    for material in ours:
        composition = _composition(material)
        if composition:
            by_elements[frozenset(composition)].append(material)

    curated: Dict[str, list] = defaultdict(list)
    names: Dict[str, str] = {}
    for r in reference.to_dict("records"):
        value = r.get("conductivity_S_cm")
        if value and value > 0 and _room(r.get("temperature_K")):
            key = _plain_key(r["composition"])
            curated[key].append(value)
            names.setdefault(key, r["composition"])
    rows = []
    for key, values in curated.items():
        composition = names[key]
        parsed = _composition(composition)
        found = [m for m in by_elements.get(frozenset(parsed or {}), []) if same_material(m, composition)]
        row = {"reference": reference["reference"].iloc[0] if len(reference) else "", "composition": composition,
               "curated_S_cm": median(values), "curated_entries": len(values), "our_material": "", "our_S_cm": None,
               "our_values": 0, "our_papers": 0, "decades": None}
        if found:
            points = [p for m in found for p in ours[m]]
            mine = median(v for v, _ in points)
            row.update(our_material=" · ".join(sorted(found)), our_S_cm=mine, our_values=len(points),
                       our_papers=len({paper for _, paper in points}),
                       decades=round(math.log10(mine / row["curated_S_cm"]), 3))
        rows.append(row)
    return pd.DataFrame(rows, columns=AGAINST_COLUMNS)


def _plain_key(composition: str) -> str:
    """One key per composition (Li6PS5Cl and Li12P2S10Cl2 alike), the text when it is not a formula."""
    from .compare import _composition
    parsed = _composition(composition)
    if not parsed:
        return str(composition).strip().lower()
    return "".join(f"{el}{parsed[el]:.4f}" for el in sorted(parsed))


def against_summary(table: pd.DataFrame) -> Dict[str, object]:
    """How much of the curated database ours covers, and how well the values agree where both have them."""
    found = table[table["our_material"] != ""]
    apart = found["decades"].abs()
    return {"curated": len(table), "found": len(found),
            "within_0.1": int((apart <= LOOSE).sum()), "within_0.5": int((apart <= 0.5).sum()),
            "within_1": int((apart <= 1.0).sum()),
            "median_decades": round(float(apart.median()), 3) if len(found) else None}
