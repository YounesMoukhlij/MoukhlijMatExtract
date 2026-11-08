# Changelog

All notable changes to MoukhlijMatExtract are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — to be released as 1.1.0

### Removed
  window, the "Fetched DOIs" list, the `[scrape]` extra (selenium, scholarly, …) and the need for Google
  Chrome. Web scraping is now the open sources only: search, review, download the legal open-access copies,
  extract. The **2 · Web scraping** button opens that window directly (no more two-method chooser). The
  PDFs already in `WebScraping/papers/` stay and are extracted as before. The DOI collector (Fetch DOIs,
  `mme-dois`, `make doi`), which asks only open indexes (OpenAlex, Crossref, Semantic Scholar, arXiv), is
  kept: it is **1 · Fetch DOIs** of the web window, and its DOI list is searched with by **2 · Search**.

### Added

- **The computer stays awake while a long step runs.** A download of thousands of papers, or an
  extraction, stopped each time the computer went to sleep while idle (a run of one day took several).
  Downloading, extracting and the web search now keep it from sleeping (macOS: caffeinate; Windows:
  SetThreadExecutionState; Linux: systemd-inhibit), and let it sleep again when they end; the screen may
  still turn off.

- **A worked example** (`examples/`, `make demo`): two open-access CC BY papers, taken through extraction,
  ranking and classification with no network; `examples/expected_values.csv` lists the values this version
  extracts, and a test checks them.
- **Mixtures inside mixtures** — "(100−x)(0.75Li2S·0.25P2S5)·xLiBH4", "50(0.75Li2S·0.25P2S5)·50LiBH4",
  "xLiI·(100−x)(…)" — are read as one material: at a stated x, that member with its composition.
- **A value of x pages after the series** ("The x = 50 samples …") goes to that member when the paper has
  named only one series this x fits (`material_link` = `paper_series`).
- **Only legally obtained papers in a published dataset.** `mme-release` releases a web paper when the record
  of the legal source it was downloaded from is kept with it, and the authors' own PDFs (part 1); it leaves
  out — of the databases, and of the ranking and the classification, made again without them — any paper
  the log of an earlier downloader records as coming from a shadow library, and any downloaded PDF with no
  record of its source, listing them by DOI in `excluded.csv` and in the datasheet (`--keep-unrecorded`
  keeps them, for a private copy).
- **docs/LIMITATIONS.md**: what the program does not do well, with the measurements (recall against the
  curated databases, values only in figures, compositions, units, components, provenance, platforms).
- **CI on Windows and macOS**, and a job that installs the built wheel in a clean environment and runs every
  command from outside the source folder, and checks that no `.env`, ledger or test is shipped.
- **mme-eval reference** (`make eval-reference`): recall against curated databases — OBELiX and the
  Liverpool Ionics Dataset, downloaded at run time from their publishers — on their own papers: their
  legal open copies are fetched into `Evaluation/reference/papers/` (PDFs added by hand are read too),
  extracted apart from the user's databases, and each curated entry is looked for among the extracted
  ionic conductivities (composition, value within 0.1 decade / 2 %, temperature). Report and every entry.
- **mme-eval score --predictions** (`PREDICTIONS=`): other tools' values (ChemDataExtractor, an LLM, …) for
  the annotated papers, scored the same way, side by side in `comparison.md`, with the F1 difference, its
  interval and a p-value from a paired bootstrap.
- **Reproducibility.** `requirements.lock`: the exact versions the results were made with (`make lock`,
  `make install-locked`). `run_manifest.json` in every results folder — extraction, ranking,
  classification, evaluation, release: one entry per run with the command, settings, software version and
  git commit, spaCy language model, Tesseract, Python and package versions, counts, and the rows and
  SHA-256 of every file. `papers.csv` gains `extracted_with` (the version and language model that read
  each paper). A missing language model is now said aloud instead of silently falling back.
- **The data dictionary**: every table and column described in `LocalExtraction/schema.py`, written next to
  each database (`data_dictionary.csv`, a `data_dictionary` sheet of `database.xlsx`) and as
  `docs/DATA_DICTIONARY.md` (`make dictionary`); a test fails when a column is not described or the
  document is out of date.
- **mme-release** (`python -m Release`, `make release`): the dataset in one folder and one `.zip`, ready
  for Zenodo — every value of every paper; the text copied from a paper only where its license lets
  anyone share it (CC BY, CC0, public domain), elsewhere the reason and the page to read it on; the data
  dictionary, the run manifests, `requirements.lock`, a datasheet (README.md, after "Datasheets for
  Datasets", its collection section filled in from the job file) and `SHA256SUMS`. `--finish` seals a
  release again once its README is completed; `--keep-text` keeps every text (not for a public deposit).
- `.zenodo.json` (the software's record for Zenodo); Python 3.13 in the classifiers and CI.
- **`mobile_ion`** in the tables of the four transport quantities: the species that moves (Li+, Na+, …,
  O2-, electron, or another element such as Co of a cathode's cross-diffusion), read off the value's
  sentence, else from the composition and the paper's main ion, with its `basis` ("ion: stated (…)" /
  "assumed (…)"), counted in `n_assumed`.
- **`plausibility`** in the same tables: `in range`, or `check: …` for a value outside the range known for
  ion conductors (0.05–1.5 eV, 1e-12–0.1 S/cm, …) or carried by another species than a conducting ion.
  **The ranking leaves those values out** (a 0.01 eV misreading ranked first; the activation energy of
  Co diffusion in LLZO was ranked as LLZO's); `mme-rank --include-flagged` (`make rank INCLUDE_FLAGGED=1`)
  keeps them. The ranking's filters now read "all values in range" by default.
- **`equation_basis`** in `equations.csv`: `written in the paper`, or — for a sentence that only names the
  law ("Arrhenius plots of …", 9 rows in 10 before) — the law's standard form, the sentence kept in
  `context_sentence`. Rows already in a database are answered the same way when it is next written.
- Because of these three columns, a database written by an earlier version is rebuilt on its next run
  (as for every new column: the old files are kept in `previous_<date>/`), which also applies the formula
  fix above to every paper.
- **mme-eval — the accuracy of the extraction** (`python -m Evaluation`, `make eval-sheet`, `eval-score`,
  `eval-agree`). `sheet` draws papers at random (seeded, with and without extracted values) and writes an
  annotation workbook: every extracted value to mark correct / partly / wrong with drop-down lists, a sheet
  for the values missed, a link to each PDF, a guide; it never replaces a workbook already there. `score`
  gives precision, recall and F1 per property and overall at the value and the record (value + material)
  level, with 95 % bootstrap intervals over papers, the accuracy of the component and origin, the
  calibration of the confidence column (ECE, Brier), precision by text / table, the errors named, and
  every false positive and negative with its sentence; with `--source` it scores a newer run against the
  same reference. `agree` gives Cohen's kappa and the F1 between two annotators. Values are compared with
  a tolerance (1 % for activation energies, 2 % on a log scale for conductivities and diffusion
  coefficients), materials by composition (Li6PS5Cl = Li12P2S10Cl2), units converted (meV, kJ/mol, mS/cm,
  S/m, m²/s, …).
- **☰ Manual** — a button beside Requirements in the main window: every command with all its options
  (`mme-gui`, `mme-local`, `mme-dois`, `mme-web`, `mme-rank`, `mme-classify` and their windows), each with
  its `python -m` form and its `make` shortcut, typical runs, the `make` shortcuts read from the Makefile,
  a list of sections to jump to, Find and Copy all. The options are read from each command's own `--help`
  in the background (the window opens at once, then fills in; once read they stay for the session), so
  the manual cannot fall out of step with the program.
- **Open the results folder** and **Browse the CSV files…** in the window of every part (Local extraction,
  Web scraping, Ranking, Classification). The browser lists every CSV file of the part's results folder
  and its subfolders (for web scraping, also the review list and the DOI list), with size and date; a
  file is read on a working thread — the window never waits — and shown a page at a time (100 to 5,000
  rows; first, previous, next, last, go to row), so big files browse as quickly as small ones; a search
  over every column and a sort by any column (numbers as numbers) run on a working thread too; the
  selected row is shown in full. Files are only read. In the Ranking window the two buttons replace
  "Open the folder", which could be used only once a ranking had been written in the same session.
- **After 2 · Search, download the papers proposed** — a box in the Web scraping window: the search goes on
  by itself into the download and, with **then extract them**, into the extraction (one click from the
  search to the database). Stopped or failed, the search goes no further; with nothing proposed, the log
  says so (no window to close).
- **Every command, with every option, in the Makefile**: `make help` lists them; an option is written
  `NAME=value` after the target (`make local WORKERS=8 OFFLINE=1`, `make rank COMPONENT="grain boundary"
  TOP=20`), a switch `NAME=1`; only what is on the make command line counts. New targets: `local-rebuild`,
  `web-check`, `web-fetch`, `web-extract`, `web-dois`, `version`, and `<part>-help` for each command's own
  help; `make test` takes `K=`, `TESTS=`, `VERBOSE=1`, `FAST=1`, `ARGS=`.
- **Clear the log**, at the top of the *Activity* tab of the Web scraping and Local extraction windows:
  empties the activity log and the log strip at the bottom of the window. Only what is shown is
  cleared — no result, ledger or file is touched — and what a step writes next appears as before.
- **1 · Fetch DOIs, then 2 · Search** (the steps renumbered: 3 · Download, 4 · Extract). Fetch DOIs is a
  button of its own, before Search; it saves the DOIs, and the window shows how many are saved and when
  they were fetched ("2 · Search uses: 40,825 DOIs saved … · 233 keywords saved"). 2 · Search fetches
  none itself: it searches with the saved keywords and the saved DOIs — checked like the keyword results
  — and says so when no DOI is saved yet (it then offers to search with the keywords only). Its steps
  show under the buttons: ▶ the one under way, ✓ those done. In the terminal, `mme-web` still does both
  in one command when `search.collect_dois: true`, and prints its steps. Stop (or Ctrl-C) during Fetch
  DOIs keeps what it collected; Fetch DOIs no longer takes over Ctrl-C inside another step.
- **The watcher** (web scraping): a search of one keyword in one source, or the download of one DOI,
  that a site refused — too many requests (HTTP 429), busy (5xx), no answer — is no longer taken for an
  answer. It goes on a watch list kept in the ledger, is checked again after 2, 5, 10 then 15 minutes
  (the status line counts down; Pause and Stop work during the wait), and what is still refused is
  checked first by the next run. A refused try does not count against a paper's three tries; six
  refusals of one check give it up. Each step ends with the watcher's report — keywords and searches
  checked, DOIs checked and how they ended, what a later try brought, what still waits, for this run
  and in total — in the log and on the card (*keywords checked*, *DOIs checked*, *waiting*).
  Fetch DOIs re-asks its refused keyword searches the same way and reports its totals.
  This also fixes a paper whose lookups were all refused being marked *closed — no legal copy*: it
  is now *waiting*.
- **Eleven more places to search, three more to find a copy** (web scraping, now 25 search sources and
  17 copy sources; each tested against the live service, November 2026):
  - without a key: **Zenodo**, **DataCite** (repository and research-centre DOIs), **PLOS**, **NASA NTRS**,
    **Figshare** (university repositories; supporting-information files left out), **OSF Preprints**
    (ECSarXiv, engrXiv, …, through SHARE), **LA Referencia** (Latin America and Spain), **theses.fr**
    (French doctoral theses, with their full text in HAL when public);
  - on request: **The Lens** (`LENS_API_TOKEN`: institutional subscription or non-commercial trial),
    **Dimensions** (`DIMENSIONS_API_KEY`: free for research, on application), **BASE**
    (`BASE_ACCESS=yes` once BASE has registered your network). Their lines are in the `.env` file, empty,
    with where each is had; a source without its key is skipped, as before;
  - copies: the **publisher's page** of an open-access journal (MDPI, Frontiers, PLOS, BMC, Nature
    Communications, RSC Advances, …; robots.txt of the publisher respected), **Zenodo** and
    **DataCite** (repository copies registered under the article's DOI);
  - a repository page found by a second source is kept beside the first source's page (new ledger
    column `copy_pages`, added to an existing ledger by itself) and tried as `repository`;
  - licences written with a version (`cc-by-4.0`, `cc0-1.0`) are spelled like the others (`cc-by`, `cc0`).
  Not added, and why, is in `WebScraping/averageScrap/README.md` (bot checks, no interface for programs,
  paid databases, shadow libraries).
- **Pause / Resume** next to Stop in every window (local extraction; web search, download and extract).
  What is under way finishes, then the step waits; nothing is cut halfway through a download.
- **Waiting for the internet**: when a web request fails and the computer is offline, the step says
  "No internet connection — waiting for it to come back", checks every 10 s, then sends the same
  request again — instead of every paper of the outage failing at once (and a site's robots.txt that
  could not be read while offline closing that site for the rest of the run). Local extraction still
  works offline: its metadata lookups do not wait.
- **Buttons that answer the mouse**, in every window: a button lights up (blue tint) under the mouse with a
  hand pointer, turns deep blue while pressed, and fades when it cannot be used. The button of the step
  that is running stays blue until the step ends (Pause stays blue while paused), so the window always
  shows which button was pressed. The colours follow the system's light or dark appearance; every other
  widget keeps its native look.
- **When papers are not found**, the download says why in a message. If Unpaywall refused the contact
  e-mail (a made-up or mistyped address — it answers HTTP 422; before, this was silent and every paper
  came out "not found"), it says so and offers to open **API keys…** to set your own academic or
  professional address. Otherwise it lists the papers without a legal copy and what can still help: the
  Elsevier and Wiley keys, the university network or VPN, the library or the authors. (Another real
  e-mail would not help: the open sources answer every real address the same.)
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
  - `mme-web` skips a search a source answered in the last 30 days (`--refresh` runs it again),
    an `ids_file` entry already in the ledger, and prints `Already fetched` for each paper already
    downloaded. A PDF already in `WebScraping/papers/` (also one named after its DOI) is used
    instead of being downloaded again.
  - `mme-rank` and `mme-classify` print `Already ranked` / `Already classified` and stop when the
    databases, options and code have not changed since the last run (a `.mme_done.json` in the
    output folder records it); `--force` runs them anyway.
- `mme-gui --help` and `mme-gui --version`, like the other commands (before, they opened the window).
- The README describes the project and holds a full user manual: installation (PyPI or source, in a
  virtual environment), each of the four steps from the window and from the terminal with their
  options, the output files, the ranking classes, and troubleshooting.

- **Search settings…** — the settings of the web search (`configs/sse.yaml`) as a form, in the Web
  scraping window (it replaces **Edit…**). It offers only what
  may be changed, each number within bounds (results per source 1–1000, downloads at once 1–8, largest
  PDF 1–500 MB, minimum score 0–20), sources and properties as boxes to tick, marks a source whose key
  is missing, keeps the file's comments and `# headings`, and has **Reset to defaults**. The folder of
  the PDFs and the job's name are shown as fixed. A window whose step is running opens it once the step is done.

- A **results browser**: **Results…** next to each part in `mme-gui` (and **Browse every table** in
  the extraction windows and on the results cards) opens every table of the part — the list of tables
  with their row counts, every column of the chosen one, a search over all columns, sorting, and every
  cell of the selected row; for the web part also the candidates of the search; for
  the ranking each component's tables; for the classification its summaries.
- A **results card** at the end of every step of every window: the outcome (done, with problems, stopped,
  failed, nothing new), the time it took, tiles with the numbers, the main findings (the lowest
  activation energies, the top materials, the largest classes — each with its article) and buttons for
  the next step. The window rings when a step ends.
- The **article title in every results CSV**: `title` after `paper_id` in every table of the extraction
  databases and of the class folders; `articles` (and `source_title`) in the ranking's and the
  classification's tables of materials. An existing database gets the
  column from its papers.csv, without extracting again. The window's table of activation energies shows
  the article instead of the file name.
- The in-app guide (the **Requirements** button of `mme-gui`) tells of Search settings, Pause, the main
  results folder, the results cards, the skipping of work already done and Delete outputs.
- **Create / Open the main results folder** in the main window (`mme-gui`): it makes
  `~/MoukhlijMatExtract` with every part's folders, then opens it. The main window no longer makes the
  folder by itself when it starts; opening a part still does.

### Changed

- **License: GNU AGPL-3.0-or-later** (was MIT). MoukhlijMatExtract reads PDFs with PyMuPDF, which is
  licensed under the AGPL-3.0; a program built on it must be shared under the same terms, so the MIT label
  did not hold. `LICENSE`, `pyproject.toml`, `CITATION.cff`, `.zenodo.json`, the README and the windows say so.
  what came with it); it is written from the cleaned environment.

- `mme-eval sheet` draws only the papers `mme-release` would publish (a recorded legal copy, or the authors'
  own PDFs), so precision and recall describe the deposited dataset; `--all-papers` draws from every paper.
- The ChemDataExtractor baseline reads each PDF in its own process, two at a time (about 3 GB each), stops a
  paper after an hour (`--timeout`) and goes on where a stopped run left off.
- **The ranking ranks each transport component on its own** — bulk, grain boundary and total — each
  with its own ranks and classes, written to `results/bulk/`, `results/grain_boundary/` and
  `results/total/` with `results/summary.csv` beside them. Before, a material's Ea was the median of its
  values of every component together. The window has a tab per component; the terminal shows each
  ranking under its own heading; each report names its component. `--component` ranks one only. The
  single mixed ranking an earlier version left at the top of `results/` is taken away.
- Windows open at a size that fits the screen and can be made smaller; the header's controls stay
  visible when a window narrows.
- Hints and status lines are readable in dark mode (they were dark grey on a dark background).
- A lookup service that does not answer at all (after its retries) is left alone for the rest of the
  run at once, instead of after three papers: OSTI timing out cost over two minutes a paper.
- The job loader refuses numbers outside those bounds, with the setting named.
- Each command's help shows the command it was started with (`usage: mme-rank …`) and points to its
  window as `mme-rank gui`, `mme-classify gui`, … (`python -m …` still works and is shown when used).
- **Existing data: add to it, or start a new database — the user chooses.** When the results folder
  already holds data and there are new PDFs to read, Local extraction asks: **Add the new articles to it**
  or **Start a new database** (the present files moved to `previous_<date>/`, nothing deleted, every PDF
  read again), or Cancel. A database of an earlier version is no longer rebuilt as the only way on: when
  every column it lacks can be worked out from its rows (moving ion, plausibility, `extracted_with`,
  `equation_basis`), "Add" brings its tables up to date in place — nothing extracted again, a copy kept in
  `previous_<date>/` — and adds the new articles (`StrictExporter.upgrade`). Web extraction asks the same
  when its database comes from an earlier version. In a terminal `mme-local` / `mme-web` ask a/n/q; a
  script keeps the data and adds to it; `--rebuild` starts a new database without asking. The benchmark
  (`mme-eval reference`) always re-extracts what an earlier version read.

### Fixed

- A lone "xLiBH4" (a part of a mixture whose other parts were not read) was taken for a series, and its
  x = 50 member for LiBH4.
- The general formula of a series with a group times x was written "Li7-xBxPH(4.0)*(x)S6-x"; it is
  "Li7-xBxPH4xS6-x".
- `mme-local --version` and `mme-web --version` warned that no spaCy model is installed (and loaded it):
  the warning now comes when an extraction starts.
- Broken links between the READMEs (renamed headings, paths one folder short).
- Unused imports reported by pyflakes.

- `mme-release` released no paper that an earlier downloader had taken from a shadow library, even after a
  legal copy of it was downloaded again: the legal source recorded with the copy extracted now comes first.
- **Conductivities in S/m** (and mS/m, µS/m) were not read: "0.12 S m−1" is 0.0012 S/cm now.
- **Composition series.** A value given for one member of a series is that compound's: with the paper's own
  label of the series and x ("LLBZT with x = 0.1" → Ba0.1Li6.6La2.9Zr1.5Ta0.5O12), with x in a sentence
  after the one naming the series ("For x = 0.25, …"), and in a table with a column of x values under a
  caption naming the series.
- **The component of a conductivity column**: "σ bulk", "σ g" (grain), "σ gb", "σ_GB", "σ tot" headers gave
  no component (it was assumed); they give bulk, grain boundary and total now ("σT", σ × T, does not).
- **A PDF already in the folder was taken as fetched**, whatever its source: a copy with no record of a legal
  source (put there by hand, or by an earlier tool) is no longer; a legal copy is looked for and replaces it.
- **Installed from PyPI, checked as a new user would** (the wheel installed into a clean environment, run
  from another folder with an empty home): every command and option works. Fixed on the way:
  `mme-eval sheet` crashed when the papers drawn had no extracted value; the manual showed each command as
  `python -m LocalExtraction …` instead of `mme-local …`; `--version` was missing from four commands and
  `mme-rank` reported "SelectingTopMaterial 1.0.0" (also written into its workbook and JSON as the program
  that made the ranking) — every command now prints "MoukhlijMatExtract <version> (<command>)", and every
  part records the package's version; a release made without `requirements.lock` (a pip install has none)
  now records the installed packages, pinned, in its place.
- **A damaged PDF entered the database empty**: a download that stopped part-way (no page can be read)
  was recorded as a paper with no material. It is now reported as failed — "the file is damaged or
  incomplete; download it again" — and kept out of the database.
- **The DOI of a web PDF named after it**: when the PDF prints no DOI and its source left no record, the DOI
  its file name gives (`10.1002_aenm.201570133.pdf`) is looked up, and kept only when the work it names has
  its title printed on the first page.
- **mme-release** says which database it leaves out (no papers.csv, or a rebuild not finished) and warns
  when a database is only partly rebuilt, instead of releasing without it or with part of it silently.
- **mme-eval score**: the columns of the summary stay aligned with long property names.
- **Python 3.11**: `Release/release.py` used quotes nested in an f-string, which only Python 3.12+ reads
  (the package states 3.11): `mme-release` would not start on 3.11.
- **Ranking and Classification** say when a database they read is only partly rebuilt (a run was stopped).
- **No window freezes** (each measured with a 50 ms heartbeat under the real event loop, every button
  pressed): the Local extraction window loaded the PDF reader and the language model to open (3.6–5.8 s
  frozen) — they are loaded by the run's own thread now; the hub loads pandas and each part's code behind
  itself, so every window opens in 0.2–0.3 s (was 0.7–1.2 s); the Results window reads its tables on
  another thread (was 1.3 s frozen for the web database, growing with it) and shows at most 5,000 rows at
  once (a 40,000-row DOI list froze it 2.4 s; the search finds the others); the ranking runs on its own
  thread (it froze the window while the databases were read and the files written); the unit registry is
  built on first use. Longest freeze left: 0.8 s, while an extraction keeps the processor busy.
- **Elsevier's first page taken for the paper**: for a paper the subscription does not cover, Elsevier's API
  can answer with the article's first page only — dense enough to pass the PDF check. A one-page PDF from
  Elsevier is now refused ("only the first page"), and the paper stays to be fetched another way.
- **Closed papers refused off the university's network are said, and not given up on.** The API keys
  window says, on the Elsevier and Wiley cards, that their keys download the closed papers only on the
  university's network (campus or VPN) — or, for Elsevier, with the institutional token. A refusal (HTTP
  403) reads "not entitled" with the same advice, the end of a download counts these papers and says why,
  and Check setup says when the Elsevier key has no institutional token. Such a refusal no longer counts as
  one of a paper's three tries: three downloads from home used to give up on papers that the university's
  network would have got.
- **Results window**: "Open the paper at doi.org" works on every row of a paper — a value, a material —
  not only on the Papers table (the DOI is taken from papers.csv by paper_id).
- **Windows**: a Tk variable freed by a worker thread (extraction, download) is released on the main
  thread, instead of calling Tcl from that thread ("main thread is not in main loop" when a window closed
  while a run went on).
- **Conductivities in inverse ohms were not read**: "Ω−1 cm−1", "(Ω cm)−1", "ohm-1 cm-1", "mho/cm" — the unit
  of most papers before ~2010 — gave no value; they are read as S/cm now. Found by comparing with OBELiX.
- **A publisher's symbol font read as other letters** (Wiley-VCH): "2.9Õ10¢9 W¢1cm¢1" is 2.9 × 10−9 Ω−1 cm−1;
  the times sign, the minus and Ω are put back where they stand in a value.
- **`raw_value` was stored as Python text** — `('1.65', 'eV')` — in every value table; it is now as the
  paper writes it (`1.65 eV`). The rows already in a database are rewritten so when it is next written.
- **Formulas whose subscripts the PDF set apart were cut**: "Na 3 PSe 4" was read as the material `PSe`,
  "Li 6 PS 5 Cl" as `PS`. The text is now put back together before reading ("Na3PSe4",
  "Li6.4La3Zr1.4Ta0.6O12", "Li1.3Al0.3Ti1.7(PO4)3", "LiNbO3"), and only where it is a formula: prose, units
  ("LiPON 2 µm"), XPS lines ("Ni 2 p") and acronyms ("SI 2") stay as they are.
- A window test of Pause waited a fixed 0.2 s for the status to change and failed under load; it now
  waits for the change.
- **`mme-rank --help` and `mme-classify --help`** (and their `gui --help`) created `~/MoukhlijMatExtract`
  and its folders before printing; the folders are now made only once the options are read.
- **`mme-dois --help`** named itself `get_dois.py`; it now says `mme-dois` (or its `python -m` form).
- **The commands in the Requirements guide** were shown in a proportional font: `("TkFixedFont", 11)` is
  read by Tk as a family that does not exist. They now use the platform's fixed-width font.
- **The Web scraping window opened in 3.75 s** with a reviewed list of 31,842 papers: it read the review
  list's decisions one database query per row, then every paper, on the window's thread. The decisions
  are now read in one query (1.5 s → 0.4 s, also at the start of each download), and both are read on a
  working thread: the window is drawn in 1.2 s and the table fills just after, without freezing it.
- **then extract them** extracted only the PDFs the same download brought: a PDF downloaded earlier and
  never extracted (a download stopped, or run without the box) stayed out of the database. It now
  extracts every downloaded PDF not in the database yet. (Checked with the real extraction.)
- The window tests could abort Python ("Fatal Python error: Aborted"): a closed test window left to the
  garbage collector was freed by a working thread of a later test, which Tk does not allow. The windows
  are now freed on the main thread after each test, and a step still under way is stopped and waited for.
- Options of the windows that were accepted and then ignored: `python -m WebScraping gui --job … --output …
  --workers …` opened the window with the defaults (and `mme-web gui` skipped the *Before you start*
  question) — both now open the same window with the options given; `mme-local gui --offline` still
  looked every paper up in OpenAlex — it now reaches the extraction.
- **After Stop the web window could stay on "Stopping …" with every button disabled**, until it was
  closed and opened again. Three causes, all fixed: the window asked whether the step's thread was still
  alive — which it is for a moment after it has said it finished — and, reading it then, kept the
  buttons disabled for good; each log line was written into the log on its own, so a long search left
  thousands waiting in front of the message that the step was over; and the cards and the table read
  the whole ledger (31,000+ papers) on the window's thread after each step. Now a step says itself when
  it is over, the log takes lines in batches and the window empties its queue by time, and the list of
  papers is read once, by the step. Measured on a real search stopped after 10 s / 30 s: the buttons
  are back after 1.7 s / 4.8 s (what was found is scored and saved first), the window never freezes
  longer than 0.35 s, and the status says where things are. The local extraction window had the same
  first fault; fixed the same way.
- **The Web scraping window opened slowly** (5.4 s with a ledger of 31,722 papers, more on a cold
  start): it loaded the extraction (spaCy, PyMuPDF's layout models) before anything was shown, and read
  every paper before drawing the window. Now those load when an extraction or a download needs them,
  the window is drawn first and the list of papers fills it right after (2.4 s in all, the same
  measure), reading the ledger is faster, and filtering the Candidates tab or typing in its search box
  no longer reads the ledger again at each key (1.8 s → 0.09 s).
- **The DOI list of Fetch DOIs is part of the search**, checked like the keyword results. It was used
  only through **Add the DOI list** (or `mme-web --dois`), and then every DOI was marked yes without
  the topic check — tens of thousands of papers, many off topic, would have been downloaded. Now the
  job's `search.doi_list` (`WebScraping/Fetch_DOIs/dois.csv`) is taken in by **1 · Search** and
  `mme-web`; each new DOI gets its OpenAlex record (abstract, open copies) and the same topic score and
  review as the keyword results, and only those on topic are proposed. A DOI-list paper not looked up
  yet (a search stopped, OpenAlex refusing) stays new instead of being declined on its bare title; a
  DOI OpenAlex does not know is not asked again by every search.
- **API keys…** opened from the *Before you start* question did not answer the mouse: the question
  holds the mouse while it waits, so Save, Cancel, the boxes and the scrolling of the keys window did
  nothing. The keys window now takes the mouse while it is open and gives it back when it closes. Its
  list of cards also scrolls with the mouse wheel over a card (the wheel stopped as soon as the
  pointer moved onto one).
- **"Too many requests" (HTTP 429)**, which arXiv answers when one network address asks too much
  (`arxiv: the search for '…' stopped early: HTTP 429`). The client waited only 2, 4 and 8 s, then went
  back to the same pace and ran into the limit again, query after query. Now a 429 is followed by
  pauses of 15, 30 and 60 s (or what the site asks for), that site gets one request every 6 s and
  more (doubled at each new 429, up to 30 s) for the rest of the run, and a source that cuts three
  searches in a row short this way is skipped until the next run instead of costing minutes per
  query. The message says that the search was cut short and is run again next time; what it found
  is kept. Fetch DOIs pauses the same way.
  **arXiv no longer stops**: at its first 429 the arXiv source goes on through OpenAlex's copy of the
  arXiv catalogue (every arXiv paper, with its arXiv PDF) for the rest of the run — in a live test,
  146 and 167 arXiv papers for two queries in about 3 s each — and uses arXiv's own search again
  next run.
- **Stop, then going on** (web window and terminal). Stop could take minutes to end a step while a
  site was slow or rate-limiting — Fetch DOIs retried a `429 Too Many Requests` up to five times with
  waits the button could not reach — and all the buttons stayed grey meanwhile, so the step could not
  be started again. Now:
  - Stop ends a step at once, also in the middle of a web request (its answer is thrown away), and
    every wait between retries (Fetch DOIs, the metadata lookups of the extraction) is one that Pause
    holds and Stop ends; a site's `Retry-After` is followed up to one minute.
  - The same button goes on where the step stopped: **1 · Search** skips the searches already
    answered and runs again the one cut short; **2 · Download** fetches the papers left; **Fetch
    DOIs…** skips the keywords already done. A stopped search says “Search stopped” (it said
    “Search finished”).
  - Ctrl-C in `mme-local` and `mme-web` stops as Stop does: what was finished is saved, the next
    stage does not start, and the same command goes on from there. A second Ctrl-C quits at once.
    Before, the papers already queued kept downloading after Ctrl-C without being recorded, and were
    downloaded again by the next run.
- `mme-rank --component "grain boundary"` matched no value: the database writes `grain_boundary`. Any
  spelling of a component is now understood.
- A class folder with no value of one quantity (e.g. no diffusion coefficient) wrote that table with the
  header `database,material_key`; it now has the table's own columns.
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

[1.0.0]: https://github.com/YounesMoukhlij/MoukhlijMatExtract/releases/tag/v1.0.0
