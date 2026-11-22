# WebScraping/sidecar.py
"""Next to every PDF the web project fetches sits a small JSON file with its provenance: the DOI,
where the file came from, under which license, when, and a checksum. The ledger holds the same, but
the sidecar travels with the file — it survives deleting the ledger, and it is what the extraction
pipeline reads to put `origin`, `source_url`, `license`, ... into papers.csv."""

import json
import os
from typing import Any, Callable, Dict


def sidecar_path(pdf_path: str) -> str:
    return os.path.splitext(pdf_path)[0] + ".json"


def write_sidecar(pdf_path: str, data: Dict[str, Any]) -> None:
    with open(sidecar_path(pdf_path), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def read_provenance(folder: str) -> Callable[[str], Dict[str, str]]:
    """A function giving, for a file name in `folder`, what is known about where it came from: the
    metadata a source reported (better than what can be guessed from the PDF) and its provenance.
    Empty for a file with no sidecar, e.g. a PDF dropped into the folder by hand."""
    def provenance(filename: str) -> Dict[str, str]:
        path = sidecar_path(os.path.join(folder, filename))
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        def text(key: str) -> str:
            value = data.get(key)
            return "; ".join(value) if isinstance(value, list) else str(value) if value not in (None, "", 0) else ""
        mapping = {
            "title": "title", "authors": "authors", "journal": "journal", "doi": "doi",
            "publication_year": "year", "source_service": "source_service", "source_url": "source_url",
            "license": "license", "retrieved_at": "retrieved_at", "file_sha256": "sha256",
            "openalex_id": "openalex_id",
        }
        return {out: text(key) for out, key in mapping.items() if text(key)}
    return provenance
