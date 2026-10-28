# Changelog

All notable changes to MoukhlijMatExtract are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-10-25

First public release.

### Added
- **Part 1 · LocalExtraction** — extract structured data from your own PDFs (text, tables, figures,
  equations, OCR) into a database of linked CSVs, an Excel workbook and JSON. No data cell is left
  empty: every value carries a `basis` saying whether it was stated, inferred or assumed.
- **Part 2 · WebScraping** — two methods that build one database:
  - *averageScrap* — search 14 open sources (OpenAlex, arXiv, Crossref, Semantic Scholar, …),
    screen, fetch the legal copies and extract them.
  - *Fetch_DOIs + moukhlij4scraping* — collect a topic's DOIs, fetch a PDF for each, extract.
- **Part 3 · SelectingTopMaterial** — rank the materials by activation energy into Superionic /
  Performant / Acceptable / Rejected classes.
- **Part 4 · Classification** — sort the materials by crystal family and structure family, one
  database per class (with bulk / grain-boundary / total sub-classes).
- **One GUI** (`mme-gui` / `python -m mme_gui`) — a hub window with a button for each part.
- Installable package (`pip install .`) with the `mme-gui`, `mme-local`, `mme-web`, `mme-rank`,
  `mme-classify` and `mme-dois` commands; `make` shortcuts; and a test suite run by `make test`.

[1.0.0]: https://github.com/YounesMoukhlij/AutoMatExtract/releases/tag/v1.0.0
