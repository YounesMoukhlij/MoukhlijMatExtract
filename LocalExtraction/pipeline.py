# LocalExtraction/pipeline.py

import concurrent.futures
import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set
from urllib.parse import unquote, urlsplit

import pandas as pd

from . import metadata, runcontrol
from .exporter import CATEGORY_FIELDS, StrictExporter, read_table
from .extractor import ExtractorEngine
from .models import ExtractedField, PaperData
from .parser import DocumentParser
from .provenance import Run
from .ranking import Ranker

# Papers are saved to the database in batches of this many, so a crash or a Ctrl-C part-way through
# a long run loses at most one batch instead of everything.
BATCH_SIZE = 50
_META_KEYS = ("title", "authors", "journal", "doi", "publication_year")
_MISSING = (None, "", "NONE")
# A file named after its DOI, as the web part saves them: 10.1002_aenm.201570133.pdf
_DOI_NAME = re.compile(r"^(10\.\d{4,9})_(\S+)$")


def doi_of_name(filepath: str) -> str:
    """The DOI a file name gives ("10.1002_inf2.12487.pdf" → "10.1002/inf2.12487"), or "". Only a
    candidate: it is kept when the work it names has its title printed on the first page."""
    found = _DOI_NAME.match(os.path.splitext(os.path.basename(filepath))[0])
    return f"{found.group(1)}/{found.group(2)}" if found else ""


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_title(a: str, b: str) -> bool:
    fold = lambda text: re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
    return len(fold(a)) >= 20 and fold(a) == fold(b)


@dataclass
class _Work:
    """One PDF to extract: its name, where it is, and the id its paper gets in the database."""
    filename: str
    path: str
    paper_id: str
    # Papers of the database already under this file name: the paper id and how it is known
    # (title, DOI). A different file under a known name is either one of them again (the same DOI or
    # title) or another paper.
    namesakes: List[Dict[str, str]] = field(default_factory=list)


class NaLiXPipeline:
    def __init__(self, input_dir: str, output_dir: str,
                 provenance: Optional[Callable[[str], Dict[str, str]]] = None,
                 properties: Optional[Iterable[str]] = None, require_material: bool = False,
                 origin: str = "local", lookup: bool = False):
        """`provenance` (optional) gives, for a file name, what is known about it besides its text:
        the metadata a source reported (better than a guess from the PDF) and where it came from.
        `properties` (optional) limits the output to the wished properties; `require_material` drops
        the numeric values that cannot be tied to a material. `origin` is recorded for every paper.
        `lookup` completes each paper's title, authors, journal, DOI, year and license from OpenAlex
        (metadata.py) — off by default so that nothing goes on the network unless asked."""
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.provenance = provenance
        self.properties = set(properties) if properties else None
        self.require_material = require_material
        self.origin = origin
        self.lookup = lookup
        # What was found for each paper, kept next to the database so that a rebuild (or a run
        # while OpenAlex is down) keeps what an earlier run found.
        self.cache = metadata.Cache(os.path.join(output_dir, metadata.CACHE_NAME)) if lookup else None
        self.skipped = 0  # PDFs found already extracted by the last plan()

    def known_papers(self) -> pd.DataFrame:
        """The papers the database already has (papers.csv). Raises UnreadableTable when it cannot be
        read: taking every PDF for new then would add every paper a second time."""
        path = os.path.join(self.output_dir, "papers.csv")
        return read_table(path) if os.path.exists(path) else pd.DataFrame()

    def get_processed_files(self) -> Set[str]:
        """The file names already in the database."""
        known = self.known_papers()
        return set(known["filename"]) if "filename" in known.columns else set()

    def plan(self, known: pd.DataFrame, rebuilt_from: Optional[List[str]] = None) -> List[_Work]:
        """What to extract: the PDFs of the input folder the database does not hold yet — and, while
        a rebuild is under way, the papers of the archived database whose PDF is elsewhere on this
        computer (where papers.csv says it was read). A PDF is known by its name and its content:
          - a name the database has, with the same file (checksum): done already;
          - a name the database has, with another file: extracted; it replaces that paper if it turns
            out to be the same paper (the same DOI or title), else it is a paper of its own;
          - the same file as a paper already there, under another name (a copy): skipped."""
        rows = known.to_dict("records") if len(known) else []
        by_name: Dict[str, List[Dict[str, str]]] = {}
        by_content: Dict[str, str] = {}
        for row in rows:
            by_name.setdefault(row.get("filename", ""), []).append(row)
            sha = row.get("file_sha256", "")
            if re.fullmatch(r"[0-9a-f]{64}", sha or ""):
                by_content[sha] = row.get("paper_id") or row.get("filename", "")
        # While a rebuild is under way, a file keeps the id its paper had before it (known by its content),
        # and a name that belonged to another paper is not taken from it.
        archived = self._archived_papers(rebuilt_from or [])
        id_before = {row["file_sha256"]: row.get("paper_id") or row.get("filename", "") for row in archived
                     if re.fullmatch(r"[0-9a-f]{64}", row.get("file_sha256", "") or "")}
        sha_before = {paper_id: sha for sha, paper_id in id_before.items()}
        work: List[_Work] = []
        self.skipped = 0  # PDFs of the folder already extracted: each one is said and passed over
        pdfs = sorted(f for f in os.listdir(self.input_dir) if f.lower().endswith(".pdf"))
        for filename in pdfs:
            path = os.path.join(self.input_dir, filename)
            namesakes = by_name.get(filename, [])
            if namesakes and not any(re.fullmatch(r"[0-9a-f]{64}", n.get("file_sha256", "") or "") for n in namesakes):
                self._already(filename)  # recorded before checksums were: taken to be this file
                continue
            sha = file_sha256(path)
            if sha in by_content:
                self._already(filename, "" if namesakes or by_content[sha] == filename
                              else f"the same file as {by_content[sha]}")
                continue
            by_content[sha] = filename
            own = f"{filename}#{sha[:8]}"
            paper_id = own if namesakes else id_before.get(sha) or (own if sha_before.get(filename, sha) != sha else filename)
            work.append(_Work(filename, path, paper_id, namesakes))
        planned = {w.paper_id for w in work} | {w.filename for w in work}
        for row in archived:
            path = self._recorded_path(row)
            paper_id = row.get("paper_id") or row.get("filename", "")
            if paper_id in planned or paper_id in {r.get("paper_id") for r in rows} or not path:
                continue
            sha = file_sha256(path)
            recorded = row.get("file_sha256", "")
            if sha in by_content or (re.fullmatch(r"[0-9a-f]{64}", recorded or "") and recorded != sha):
                continue  # being extracted already, or another file now sits where it was: carried over
            by_content[sha] = paper_id
            planned.add(paper_id)
            work.append(_Work(row.get("filename") or os.path.basename(path), path, paper_id))
        return work

    def _already(self, filename: str, why: str = "") -> None:
        self.skipped += 1
        logging.info(f"Already extracted: {filename}{f' ({why})' if why else ''} — skipped.")

    @staticmethod
    def _archived_papers(archives: List[str]) -> List[Dict[str, str]]:
        """The papers of archived databases, the newest archive's record of a paper first."""
        seen, rows = set(), []
        for archive in reversed(archives):
            path = os.path.join(archive, "papers.csv")
            if not os.path.exists(path):
                continue
            for row in read_table(path).to_dict("records"):
                paper_id = row.get("paper_id") or row.get("filename", "")
                if paper_id and paper_id not in seen:
                    seen.add(paper_id)
                    rows.append(row)
        return rows

    def _recorded_path(self, row: Dict[str, str]) -> str:
        """Where the PDF of an archived paper is now: the input folder, or the place papers.csv says
        it was read from on this computer; "" when it is in neither."""
        here = os.path.join(self.input_dir, row.get("filename", ""))
        if row.get("filename") and os.path.isfile(here):
            return here
        url = row.get("source_url", "")
        if url.startswith("file://"):
            path = unquote(urlsplit(url).path)
            return path if os.path.isfile(path) else ""
        return ""

    @staticmethod
    def _identity(work: _Work, paper: PaperData) -> str:
        """The paper id of a PDF whose file name the database already had: that paper's, when the PDF
        is the same paper (its DOI or its title), else an id of its own."""
        doi = paper.metadata.get("doi").normalized_value if paper.metadata.get("doi") else ""
        title = paper.metadata.get("title").normalized_value if paper.metadata.get("title") else ""
        stem = os.path.splitext(work.filename)[0]
        for namesake in work.namesakes:
            if doi.startswith("10.") and doi.lower() == (namesake.get("doi") or "").lower():
                return namesake.get("paper_id") or work.filename
            if title != stem and _same_title(title, namesake.get("title", "")):
                return namesake.get("paper_id") or work.filename
        return work.paper_id

    def _restrict(self, paper: PaperData) -> None:
        """Keeps the wished data only: the chosen properties and, if asked, only the numeric values
        tied to a material (a DFT setting or a software name has no material and is left alone)."""
        for name in CATEGORY_FIELDS:
            kept = {}
            for prop, candidates in (getattr(paper, name, {}) or {}).items():
                if self.properties is not None and prop not in self.properties:
                    candidates = []
                elif self.require_material and ExtractorEngine._has_context(name.upper(), prop):
                    candidates = [c for c in candidates if c.material_id != "NONE"]
                kept[prop] = candidates
            setattr(paper, name, kept)
        if self.properties is not None:
            paper.relations = [r for r in paper.relations if r.property_name in self.properties]
            for material in paper.materials:
                material.properties = [p for p in material.properties if p.property_name in self.properties]
            paper.materials = [m for m in paper.materials if m.properties]

    def process_document(self, filename: str, path: Optional[str] = None) -> Optional[PaperData]:
        filepath = path or os.path.join(self.input_dir, filename)

        try:
            doc_parser = DocumentParser(filepath)
            raw_meta, blocks, references = doc_parser.parse()

            extra = self.provenance(filename) if self.provenance else {}
            # What a source reported about the paper beats what can be guessed from its first page.
            for key in ("title", "authors", "journal", "publication_year"):
                if extra.get(key):
                    raw_meta[key] = extra[key]
            if extra:
                # The DOI above all: the first DOI printed in a preprint is usually one of its references,
                # so for a paper the source knows, the guess is dropped when the source reported no DOI.
                raw_meta["doi"] = extra.get("doi") or "NONE"

            # The first page as read, and its title as the parser read it from the page's largest type
            # (the reading order can move a line of a title elsewhere on the page).
            first_page = " ".join(b["text"] for b in blocks if str(b.get("page")) == "1") + "\n" + raw_meta.get("title", "")
            extra = self._complete(filepath, raw_meta, dict(extra), first_page)

            # Format Metadata into ExtractedFields
            metadata_fields = {
                k: ExtractedField(v, v, 1.0, "1", "Metadata", v, "Metadata") if v != "NONE" else ExtractedField.empty()
                for k, v in raw_meta.items()
            }

            title = raw_meta.get("title", "NONE")
            extracted_raw = ExtractorEngine.extract_all(blocks, title="" if title == "NONE" else title,
                                                        references=len(references))
            ranked = Ranker.process(extracted_raw)

            paper = PaperData(
                filename=filename,
                metadata=metadata_fields,
                materials=ranked["materials"],
                electrochemical=ranked["ELECTROCHEMICAL"],
                thermodynamic=ranked["THERMODYNAMIC"],
                mechanical=ranked["MECHANICAL"],
                structural=ranked["STRUCTURAL"],
                electronic=ranked["ELECTRONIC"],
                thermal=ranked["THERMAL"],
                spectroscopy=ranked["SPECTROSCOPY"],
                dft=ranked["DFT"],
                aimd=ranked["AIMD"],
                ml=ranked["ML"],
                synthesis=ranked["SYNTHESIS"],
                characterization=ranked["CHARACTERIZATION"],
                battery_perf={},
                interfaces={},
                relations=ranked["relations"],
                workflow=ranked["workflow"],
                figures=ranked["figures"],
                tables=ranked["tables"],
                equations=ranked["equations"],
                references=references,
                origin=self.origin,
                provenance=extra,
            )
            if self.properties is not None or self.require_material:
                self._restrict(paper)
            return paper
        except Exception as e:
            logging.error(f"Failed {filename}: {str(e)}")
            return None

    def _complete(self, filepath: str, raw_meta: Dict[str, str], extra: Dict[str, str], first_page: str) -> Dict[str, str]:
        """Fills what the paper's description lacks: from OpenAlex (when `lookup`), then — for a
        PDF of this computer — from the file itself. Returns the provenance to record; `raw_meta`
        is completed in place and given a `basis`."""
        from_source = bool(extra)
        with open(filepath, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        complete = all(raw_meta.get(key) not in _MISSING for key in _META_KEYS) and extra.get("license") \
            and extra.get("openalex_id")
        found, unreachable = None, False
        if self.lookup and not complete:
            found = self.cache.get(digest) if self.cache is not None else None
            if found is None:
                doi = raw_meta.get("doi", "")
                named = doi_of_name(filepath) if doi in _MISSING else ""
                found, unreachable = metadata.find(named or doi, raw_meta.get("title", ""), first_page,
                                                   trusted_doi=from_source and bool(extra.get("doi")))
                if found and named and found.get("doi", "").casefold() == named.casefold():
                    found["basis"] += " — the DOI its file name gives"
                if found and self.cache is not None:
                    self.cache.put(digest, found)
        if found:
            for key in _META_KEYS:
                # A source's own report stands; for a PDF of this computer, the matched work replaces the guess.
                if found[key] and (not from_source or raw_meta.get(key) in _MISSING):
                    raw_meta[key] = found[key]
            for key in ("license", "openalex_id"):
                if found[key] and not extra.get(key):
                    extra[key] = found[key]
        not_asked = "OpenAlex was not asked" if not self.lookup else (
            "OpenAlex could not be reached when it was read" if unreachable else "no OpenAlex work matches it")
        if from_source:
            raw_meta["basis"] = f"the source it was fetched from ({extra.get('source_service', 'web')})" + (
                f"; completed from {found['basis']}" if found else "")
        else:
            raw_meta["basis"] = found["basis"] if found else f"the PDF itself ({not_asked})"
        for key, missing in (("title", os.path.splitext(os.path.basename(filepath))[0]),
                             ("authors", "not printed in the PDF's metadata"), ("journal", "not printed in the PDF's metadata"),
                             ("doi", "no DOI reported by the source" if from_source else "no DOI printed in the paper"),
                             ("publication_year", "not printed in the paper")):
            if raw_meta.get(key) in _MISSING:
                raw_meta[key] = missing

        if not from_source:
            stat = os.stat(filepath)
            extra.setdefault("source_service", "a file of this computer")
            extra.setdefault("source_url", "file://" + os.path.abspath(filepath))
            extra.setdefault("retrieved_at", datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"))
            extra.setdefault("file_sha256", digest)
        extra.setdefault("license", "not stated (a copy on this computer)" if not from_source else "not stated by the source")
        extra.setdefault("openalex_id", "not found in OpenAlex" if self.lookup and not unreachable else f"not looked up ({not_asked})")
        return extra

    def execute(self, max_workers: int = 4, stop_event: Optional[threading.Event] = None,
                progress_callback: Optional[Callable[[str, Optional[PaperData]], None]] = None,
                batch_size: int = BATCH_SIZE) -> int:
        """Runs extraction over every not-yet-processed PDF and exports the results; returns how
        many papers were added to the database.

        `stop_event` (optional): when set between files, cancels every PDF still queued and
        stops after the ones already running finish — lets a caller (e.g. the GUI) request an
        early stop without losing in-flight work.
        `progress_callback` (optional): called once per PDF as soon as it finishes, as
        `callback(filename, paper_or_none)` — `None` on failure — so a caller can show live
        per-paper feedback instead of waiting for the whole batch to end.
        `batch_size`: papers are saved to the database every this many, not only at the end.
        """
        # 1. What the database holds, and what is left to extract (a rebuild under way included)
        run = Run("extraction", Path(self.output_dir), with_model=True, settings={
            "input": os.path.abspath(self.input_dir), "output": os.path.abspath(self.output_dir),
            "workers": max_workers, "origin": self.origin, "metadata_lookup": self.lookup,
            "properties": sorted(self.properties) if self.properties else "all",
            "require_material": self.require_material})
        known = self.known_papers()
        rebuilt_from = StrictExporter.pending_rebuilds(self.output_dir)
        work = self.plan(known, rebuilt_from)

        if not work:
            if rebuilt_from:
                self._bring_back(rebuilt_from)
            elif not any(f.lower().endswith(".pdf") for f in os.listdir(self.input_dir)):
                logging.info(f"No PDFs found in {self.input_dir}. Add some and re-run.")
            else:
                logging.info(f"All {self.skipped} PDF(s) in the folder are already extracted — nothing to do. "
                             "The database is up to date.")
            return 0
        new_pdfs = work

        if self.skipped:
            logging.info(f"{self.skipped} PDF(s) already extracted were skipped.")
        logging.info(f"Starting extraction for {len(new_pdfs)} new papers...")

        exporter = StrictExporter(self.output_dir)
        pending: List[PaperData] = []
        added = 0
        stopped = False

        def save() -> None:
            nonlocal pending, added
            if pending:
                exporter.export(pending, excel=False)  # the workbook is built once, at the end
                added += len(pending)
                pending = []
                logging.info(f"Saved {added} paper(s) to the database so far.")
            if self.cache is not None:
                self.cache.save()

        # 3. Process only the new files (spaCy/pint/pymatgen are safe to share read-only
        # across these worker threads — see the module-level notes in extractor.py/normalizer.py).
        # Submitted (rather than mapped) so a stop request can cancel PDFs that haven't started yet.
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Each PDF waits for its turn while the step is paused (Pause in the window)
            futures = {executor.submit(runcontrol.task(stop_event, self.process_document, w.filename, w.path)): w
                       for w in new_pdfs}
            for future in concurrent.futures.as_completed(futures):
                item = futures[future]
                filename = item.filename
                try:
                    r = future.result()
                except runcontrol.StepStopped:  # stopped in the middle of this PDF: read again next run
                    for pending_future in futures:
                        pending_future.cancel()
                    logging.info(f"Stop requested — the PDFs being read were left off (read again next run); "
                                 f"{added + len(pending)}/{len(new_pdfs)} finished.")
                    stopped = True
                    break
                if r:
                    r.paper_id = self._identity(item, r) if item.namesakes else item.paper_id
                    if item.namesakes and r.paper_id != item.paper_id:
                        logging.info(f"{filename} is a new copy of a paper already in the database: its rows replace the earlier ones.")
                    elif item.namesakes:
                        logging.info(f"{filename}: the database already has another paper of that name; this one is {r.paper_id}.")
                    pending.append(r)
                else:
                    logging.warning(f"No data extracted from {filename} (parse/extraction failed).")
                if progress_callback is not None:
                    try:
                        progress_callback(filename, r)
                    except Exception as e:
                        logging.warning(f"progress_callback raised for {filename}: {e}")
                if len(pending) >= batch_size:
                    save()
                if stop_event is not None and stop_event.is_set():
                    for pending_future in futures:
                        pending_future.cancel()
                    logging.info(f"Stop requested — cancelled remaining queued PDFs "
                                 f"({added + len(pending)}/{len(new_pdfs)} finished).")
                    stopped = True
                    break

        # 4. Export what is left (appended to the database), the papers of a rebuild whose PDF is gone,
        # then the workbook
        save()
        if rebuilt_from and not stopped:
            added += self._bring_back(rebuilt_from, excel=False)
        if added:
            exporter.export_excel()
            logging.info(f"Successfully added {added} new papers to the database.")
        try:  # what this run did, with what — appended to <output>/run_manifest.json
            run.finish({"pdfs_new": len(new_pdfs), "already_extracted": self.skipped, "papers_added": added},
                       status="stopped" if stopped else "finished")
        except OSError as error:
            logging.warning(f"The run could not be recorded in {self.output_dir}: {error}")
        return added

    def _bring_back(self, archives: List[str], excel: bool = True) -> int:
        """The end of a rebuild: the papers of the archived databases that are still not in the new one
        (their PDF is no longer at hand, so they could not be extracted again) are carried over from
        the archive as they were. Returns how many."""
        exporter = StrictExporter(self.output_dir)
        brought = 0
        for archive in reversed(archives):  # the newest archive's rows of a paper
            known = self.known_papers()
            have = set(known["paper_id"]) if "paper_id" in known.columns else set()
            missing = {row.get("paper_id") or row.get("filename", "") for row in self._archived_papers([archive])} - have
            if missing:
                count = exporter.carry_over(archive, missing)
                brought += count
                logging.info(f"Rebuild: {count} paper(s) whose PDF is no longer at hand were carried over from "
                             f"{os.path.basename(archive)} as they were (a column this version adds says "
                             f"\"not recorded\").")
        StrictExporter.rebuild_done(self.output_dir)
        if brought and excel:
            exporter.export_excel()
        return brought
