# pipeline.py

import concurrent.futures
import logging
import os
import threading
from typing import Callable, Dict, Iterable, List, Optional, Set

import pandas as pd

from exporter import CATEGORY_FIELDS, StrictExporter
from extractor import ExtractorEngine
from models import ExtractedField, PaperData
from parser import DocumentParser
from ranking import Ranker

# Papers are saved to the database in batches of this many, so a crash or a Ctrl-C part-way through
# a long run loses at most one batch instead of everything.
BATCH_SIZE = 50


class NaLiXPipeline:
    def __init__(self, input_dir: str, output_dir: str,
                 provenance: Optional[Callable[[str], Dict[str, str]]] = None,
                 properties: Optional[Iterable[str]] = None, require_material: bool = False,
                 origin: str = "local"):
        """`provenance` (optional) gives, for a file name, what is known about it besides its text:
        the metadata a source reported (better than a guess from the PDF) and where it came from.
        `properties` (optional) limits the output to the wished properties; `require_material` drops
        the numeric values that cannot be tied to a material. `origin` is recorded for every paper."""
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.provenance = provenance
        self.properties = set(properties) if properties else None
        self.require_material = require_material
        self.origin = origin

    def get_processed_files(self) -> Set[str]:
        """
        Reads the filenames already present in papers.csv so re-running the pipeline only
        processes new PDFs. Fails open (returns an empty set) if the database doesn't exist
        yet or is unreadable, so new papers are never silently skipped.
        """
        path = os.path.join(self.output_dir, "papers.csv")
        if not os.path.exists(path):
            return set()
        try:
            df = pd.read_csv(path, usecols=["filename"])
            return set(df["filename"].dropna().astype(str))
        except Exception as e:
            logging.warning(f"Could not read existing papers.csv ({e}); treating all PDFs as new.")
            return set()

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

    def process_document(self, filename: str) -> Optional[PaperData]:
        filepath = os.path.join(self.input_dir, filename)

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
        # 1. Identify which files have already been processed
        processed_files = self.get_processed_files()

        # 2. Filter the folder for only NEW, unprocessed PDFs
        all_pdfs = [f for f in os.listdir(self.input_dir) if f.lower().endswith('.pdf')]
        new_pdfs = [f for f in all_pdfs if f not in processed_files]

        if not new_pdfs:
            if not all_pdfs:
                logging.info(f"No PDFs found in {self.input_dir}. Add some and re-run.")
            else:
                logging.info("All PDFs in the folder have already been processed. Database is up to date.")
            return 0

        logging.info(f"Skipping {len(processed_files)} existing papers.")
        logging.info(f"Starting extraction for {len(new_pdfs)} new papers...")

        exporter = StrictExporter(self.output_dir)
        pending: List[PaperData] = []
        added = 0

        def save() -> None:
            nonlocal pending, added
            if pending:
                exporter.export(pending, excel=False)  # the workbook is built once, at the end
                added += len(pending)
                pending = []
                logging.info(f"Saved {added} paper(s) to the database so far.")

        # 3. Process only the new files (spaCy/pint/pymatgen are safe to share read-only
        # across these worker threads — see the module-level notes in extractor.py/normalizer.py).
        # Submitted (rather than mapped) so a stop request can cancel PDFs that haven't started yet.
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.process_document, f): f for f in new_pdfs}
            for future in concurrent.futures.as_completed(futures):
                filename = futures[future]
                r = future.result()
                if r:
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
                    break

        # 4. Export what is left (CSV/JSON merge into an existing database), then the workbook
        save()
        if added:
            exporter.export_excel()
            logging.info(f"Successfully added {added} new papers to the database.")
        return added
