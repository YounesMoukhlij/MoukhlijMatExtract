# Changelog

All notable changes to MoukhlijMatExtract are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- The hub (`mme-gui`) ends with an "About" section: what the project does, who made it, how to
  cite it, its version and license, and links to the repository and the author's e-mail.
- A **Delete outputs…** button for each part, in the hub (`mme-gui`) and in each part's window.
  It lists what the part wrote (with file counts and sizes), deletes only what is ticked, and
  moves it to the Trash (new dependency: `Send2Trash`). Inputs (your PDFs, the job file, the API
  keys) are never offered; a part that is running — or the web window holding its ledger open —
  cannot be emptied until it is done.
- Work already done is skipped, with a message, instead of being done again:
  - `mme-local` / the extraction of `mme-web` print `Already extracted: <file> — skipped.` for each
    PDF already in the database.
  - `mme-dois` remembers which source answered which keyword (`dois.searched.json` next to the
    list) and prints `already fetched on <date> — skipped` for 30 days; `--refresh` asks again.
  - `mme-web` skips a search a source answered in the last 30 days (`--refresh` runs it again),
    an `ids_file` entry already in the ledger, and prints `Already fetched` for each paper already
    downloaded. A PDF already in `WebScraping/papers/` (e.g. saved by moukhlij4scraping) is used
    instead of being downloaded again.
  - moukhlij4scraping skips a DOI whose PDF is already in the folder, under either method's name.
  - `mme-rank` and `mme-classify` print `Already ranked` / `Already classified` and stop when the
    databases, options and code have not changed since the last run (a `.mme_done.json` in the
    output folder records it); `--force` runs them anyway.
- `mme-gui --help` and `mme-gui --version`, like the other commands (before, they opened the window).
- The README describes the project and holds a full user manual: installation (PyPI or source, in a
  virtual environment), each of the four steps from the window and from the terminal with their
  options, the output files, the ranking classes, and troubleshooting.

- **Search settings…** — the settings of the web search (`configs/sse.yaml`) as a form, in the web
  chooser, in method 1's window (it replaces **Edit…**) and in method 2's window. It offers only what
  may be changed, each number within bounds (results per source 1–1000, downloads at once 1–8, largest
  PDF 1–500 MB, minimum score 0–20), sources and properties as boxes to tick, marks a source whose key
  is missing, keeps the file's comments and `# headings`, and has **Reset to defaults**. The folder of
  the PDFs and the job's name are shown as fixed. A window whose step is running opens it once the step is done.

- A **results browser**: **Results…** next to each part in `mme-gui` (and **Browse every table** in
  the extraction windows and on the results cards) opens every table of the part — the list of tables
  with their row counts, every column of the chosen one, a search over all columns, sorting, and every
  cell of the selected row; for the web part also the candidates, the downloads and the DOI list; for
  the ranking each component's tables; for the classification its summaries.
- A **results card** at the end of every step of every window: the outcome (done, with problems, stopped,
  failed, nothing new), the time it took, tiles with the numbers, the main findings (the lowest
  activation energies, the top materials, the largest classes — each with its article) and buttons for
  the next step. The window rings when a step ends.
- The **article title in every results CSV**: `title` after `paper_id` in every table of the extraction
  databases and of the class folders; `articles` (and `source_title`) in the ranking's and the
  classification's tables of materials; `title` in `scrape_log.csv`. An existing database gets the
  column from its papers.csv, without extracting again. The window's table of activation energies shows
  the article instead of the file name.
- The in-app guide (the **Requirements** button of `mme-gui`) tells of Search settings, Fetched DOIs, the main
  results folder, the results cards, the skipping of work already done and Delete outputs.
- **Create / Open the main results folder** in the main window (`mme-gui`): it makes
  `~/MoukhlijMatExtract` with every part's folders, then opens it. The main window no longer makes the
  folder by itself when it starts; opening a part still does.
- **Fetched DOIs (N)…** in the moukhlij4scraping window: the DOIs collected, with their total, which
  have their PDF, which were tried without success and which were not tried yet; filter, sort, copy,
  open at doi.org, and every detail of the selected DOI.
- moukhlij4scraping looks for the **legal open-access copy** of each DOI first (method 1's sources:
  Unpaywall, OpenAlex, arXiv, PubMed Central, OSTI, HAL, publisher APIs), several DOIs at a time.
- **2 · Scrape articles** asks whether to start with the open-access copies. No (or
  method 1; a DOI tried that way is tried again once the open-access step is chosen.
- A list of DOIs is fetched in runs: `--limit N` per run (asked in the window), DOIs no source had
  skipped for 30 days (`--retry`), each DOI tried in `scrape_log.csv`, progress `[i/n]` and a summary by
  source; the window shows the step, the DOI reached and the PDFs saved.

### Changed
- **The ranking ranks each transport component on its own** — bulk, grain boundary and total — each
  with its own ranks and classes, written to `results/bulk/`, `results/grain_boundary/` and
  `results/total/` with `results/summary.csv` beside them. Before, a material's Ea was the median of its
  values of every component together. The window has a tab per component; the terminal shows each
  ranking under its own heading; each report names its component. `--component` ranks one only. The
  single mixed ranking an earlier version left at the top of `results/` is taken away.
- Windows open at a size that fits the screen and can be made smaller; the header's controls stay
  visible when a window narrows; method 2's settings and delete buttons have a row of their own.
- Hints and status lines are readable in dark mode (they were dark grey on a dark background).
- A lookup service that does not answer at all (after its retries) is left alone for the rest of the
  run at once, instead of after three papers: OSTI timing out cost over two minutes a paper.
- The job loader refuses numbers outside those bounds, with the setting named.
- Each command's help shows the command it was started with (`usage: mme-rank …`) and points to its
  window as `mme-rank gui`, `mme-classify gui`, … (`python -m …` still works and is shown when used).

### Fixed
- `mme-rank --component "grain boundary"` matched no value: the database writes `grain_boundary`. Any
  spelling of a component is now understood.
- A class folder with no value of one quantity (e.g. no diffusion coefficient) wrote that table with the
  header `database,material_key`; it now has the table's own columns.
  Chrome is started only when a page has to be read, and a Chrome that cannot start no longer ends the
  whole run.
- `mme-classify --help` gave the old folder name (`Crystal and Structure Classification/`) as the
  default output folder; it is `Classification/`.
- `make install` now also installs the project itself in editable mode (`pip install -e .`), so the
  `mme-*` commands run the code of the folder, not an older copy installed earlier.

## [1.0.2] — 2026-10-29

### Changed
- Every command now works inside `~/MoukhlijMatExtract`, whatever folder it is started from, and
  creates that folder and its own sub-folders when they are missing (`mme-local`:
  `LocalExtraction/papers` + `local_output`; `mme-web`: `WebScraping/papers` + `web_output`;
  `mme-dois`, `mme-rank`, `mme-classify` likewise; `mme-gui`: all of them).
- The Local extraction window shows its two folders as fixed paths with an **Open** button; they
  can no longer be changed with **Browse…**.

### Added
- Each time the Web scraping window opens, it asks for the user's academic e-mail (required, saved
  for next time), points to the optional **API keys**, and says that method 2 needs Google Chrome.
  Its two methods open only once an e-mail is given.

### Fixed
- The job file shipped with the package carried the author's e-mail, which was sent to OpenAlex,
  Crossref and Unpaywall in place of the user's own. It now ships empty, so the user's e-mail is used.
- OpenAlex now asks for an API key to go past the first page of a search. Without one, `mme-web`
  crashed after its first query and `mme-dois` got no DOIs from OpenAlex; both now take the first
  100 results of each search, and the API keys window says what a free OpenAlex key adds.
- The Classification window no longer shows a message box when it is opened before any database
  exists; it says to run part 1 or 2 first.
- The moukhlij4scraping window ran its steps by file paths that only existed in a clone of the
  repository, so they failed for an installed package.

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
