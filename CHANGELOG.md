# Changelog

All notable changes to MoukhlijMatExtract are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — after 1.1.0

### Added

- **“📊 Statistics…” in every window that has statistics**: a window of charts about the work done, read from that
  window's own files (never changed), each chart's finding in its title (“1 in 229 papers found yields an activation
  energy”), the numbers on the bars, light or dark like the windows. **Refresh** reads the files again (a running
  search grows); the charts are read on a working thread, so the window never waits.
  - **2 · Web scraping:** the corpus funnel (found → proposed → downloaded → extracted → with an activation energy),
    where each paper is now, papers found per search source, papers by year, the ten publishers (proposed and
    downloaded), why downloads failed, legal copies per source, searches finished per day; then the database's charts.
  - **1 · Local extraction** (and the database of a web job): values per property, activation energies by transport
    component, measured or computed and own or cited, their distribution against the electrolyte classes, the kind of
    energy, the mobile ion, why values are flagged, the distribution of ionic conductivities, papers by year.
  - **3 · Ranking:** for each component, materials per class, the 15 best materials, the evidence each rank rests on.
    **4 · Classification:** materials per crystal-structure type and per structure family, the median activation
    energy of each family. **5 · ML datasets** (after a dataset is made): the target's distribution, values per
    material, why values were left out. **Evaluation…:** precision, recall and F1 per property, and the benchmark.
  - **Save the charts (PNG 300 dpi + SVG):** every chart into `~/MoukhlijMatExtract/Statistics/PNG/` (300 dpi) and
    `~/MoukhlijMatExtract/Statistics/SVG/`, named `<window>-<job>_<chart>_<date>_<time>` so nothing is overwritten;
    always light, for print. **Open the Statistics folder** opens it.
  - matplotlib is now a declared dependency (it was installed with pymatgen).
- **Full-text search on OpenAlex: the papers that report the data, even when their abstract does not say so.**
  - **What:** a job's `search.fulltext_queries` (one per line, its phrases in quotes, e.g.
    `"activation energy" "ionic conductivity"`) finds every work whose full text holds each phrase exactly, from
    OpenAlex's index of the full texts it can read, up to `search.fulltext_max` (100,000) each, 200 to a request.
    `search.fulltext_open_only` keeps the works with a known free copy only. Needs the free `OPENALEX_API_KEY` for
    more than the first page.
  - **The screening:** the phrases count as the property words found (in the full text, worth as much as in a
    title); the topic words must still be in the title or abstract. A paper turned down before only because its
    abstract lacked the property words is scored again (not one a person turned down).
  - **How much:** "activation energy" with "ionic conductivity" is in the full text of 21,951 works;
    "activation energy" "garnet" "ionic conductivity" proposed 714 papers in a test, 229 of them turned down by
    the abstract screening of the garnet/NASICON job.
  - **Every shipped job file** has its full-text searches (domain jobs: three to five; family jobs: the family's
    names with "activation energy" or "Arrhenius" and "ionic conductivity"). Job files already in
    `~/MoukhlijMatExtract/configs` are yours and kept: add the lines in **Search settings… → Full-text searches**.
  - **The window:** a box in Search settings (tab 1), and a phase of its own in the progress of 2 · Search.
- **arXiv's bulk copy:** an arXiv PDF is first taken from arXiv's public bulk copy on Google Cloud (the one the arXiv
  dataset on Kaggle points to, kept current), the newest version, with no pause between two files; arxiv.org (15 s
  between PDFs, as its robots.txt asks) is tried when a paper is not there yet. Old identifiers
  (`cond-mat/0101001`) too.
- **`mme-web update --all`** (`make update ALL=1`): every job file, the ones never run included (searched in full),
  one after the other — the whole literature of every family and domain in one command; with `--yes` nothing waits
  for a review.
- **A doped sample named after its parent is its own material.** "Ta-LLZO", "Ga–LLZO", "Al,Ga-LLZO", "Ta-doped
  LLZO", "Ga and Al co-doped LLZO", "Al-substituted Li7La3Zr2O12" are read as "Ta-doped Li7La3Zr2O12" (and so on),
  with the parent's composition, in the value's own sentence. Before, such a value fell back on the paragraph's
  parent compound (wrong material), or was flagged and left out of the ranking. In the two web databases, 52 of 915
  and 61 of 1,041 activation energies go to their doped sample (68 of them had been left out). A single capital is
  taken for a dopant only with the word ("S-doped LLZO"; "S-LLZO" is a tag). The worked example's cited
  conductivity of "Fe-stabilized LLZO" is now `Fe-doped Li7La3Zr2O12`.
- **`paper/paper.md` and `paper/paper.bib`**: the article for the Journal of Open Source Software (883 words), every
  reference checked against Crossref and DataCite.

- **How long a step will take, said when it starts, and “⏱ Progress details”** in every window that runs a long
  step (Web scraping: Fetch DOIs, Search, Download, Extract, Re-screen; Local extraction; Classification; Ranking).
  - **The estimate:** a step starts with *“Fetch DOIs — 532 searches · estimated about 26 min (from your earlier
    runs) · done around 15:12”*. It comes from the pace each phase had on this computer in the runs finished before
    (seconds per search, per paper, per PDF, kept in `~/.moukhlijmatextract/timings.json` as a running mean). Before
    a phase has run once, a first guess is used and said to be one. The Fetch DOIs question shows the estimate before
    anything starts.
  - **The line of the step in dark yellow** while it runs (readable in light and dark mode), back to its colour at
    the end. It ends with *“about 6 min left · done around 15:12”*.
  - **“⏱ Progress details”**, beside the line, opens a window that follows the step live: started, elapsed, time
    left, expected end, pace and state; the overall progress; each phase ticked off (✓ done, ▶ now, ○ next) with its
    count, its bar, its time and its time left; what it searches or fetches now, and the counters (new DOIs, new
    papers …); a chart of the pace (items per minute); the timeline of what was searched or fetched, and when; Pause /
    Resume and Stop; “Save the timeline (CSV)…”. It stays after the step ends, to look back at the last run, and
    follows the next step when one starts.
  - **Long times read as a person says them:** 45 s · 26 min · 1 h 20 min · 14 h · 2 days 3 h · 9 days — many
    minutes in hours, many hours in days (the progress lines, the estimates, the details window, and the time a step
    took on its card).
  - **“✓ If you stop now, … is saved”**, under the line while a step runs (and in the details window), said for each
    step as it is: every DOI found so far (Fetch DOIs); the papers found so far, and the next search goes on from
    there (Search); every PDF downloaded so far (Download); every PDF already extracted, and the next extraction
    reads only the rest (Extract, Local extraction). Not said for the steps that cannot be stopped half-way: the
    classification and the ranking (they write everything at once, in seconds), the re-screen (it finishes by itself).

- **One copy of each window.** A window asked for while it is already open is not opened a second time: the open
  one comes to the front (shown again if it was minimised), and a message says *“… is already open. Only one can be
  open at a time — it has been brought to the front.”* Different windows still open side by side (rank while a web
  search runs).
  - **Which:** the five parts; Results… and Delete outputs… of each part; Requirements, Manual, Make commands, About
    & methods; the Process flow and the Classification flow; Evaluate…, API keys…, Search settings…, the browser
    helper and “Browse the CSV files…”.
  - Asked from another window, the Process flow that is already open moves its “You are here” to that window.
  - The check is in each window's own opening (`LocalExtraction/gui/single.py`), so every way to it is covered: a
    button of the main window, of a part, or a link.

- **A floating “⇄ Flow” button in every window**: it opens the **Process flow**, the whole program from scratch,
  window by window.
  - **The flow:** start (install, Requirements, the main folder, the main window). Then build the database: your own
    PDFs, or the web (choose a job → 1 · Fetch DOIs → 2 · Search → review the candidates → 3 · Download → 4 ·
    Extract). Then use it (check values by hand, ③ Ranking, ④ Classification → ⑤ ML datasets), measure the accuracy
    (Evaluate… → you annotate → the scores → benchmark and gold standard) and share it (release → Zenodo; make paper
    → the article). Each step names its window and button.
  - **“You are here”** marks the steps of the window it was opened from (all six web steps from Web scraping).
  - **A click on a step** says where to click, what it does and why it matters; the steps of the five parts have an
    “Open …” button.
  - **The button** sits where it covers no button, field, scroll bar or link, looked for again when the window is
    resized. A drag moves it, and then it stays where it was put.

- **“Add MoukhlijMatExtract to the Dock?”** (macOS): when the main window opens and the program is not in the Dock,
  a small window offers to put it there, so it starts with one click.
  - **Add to the Dock** makes `~/Applications/MoukhlijMatExtract.app` if it is missing, adds it to the end of the
    Dock (once) and restarts the Dock so it shows at once.
  - **Not now** asks again next time; **Don't ask again** is remembered. `mme-gui --install-app` / `make app` still
    make the app, to drag to the Dock by hand.
  - It waits until any other question of the main window has been answered, and is never shown on Windows or Linux.

- **Real progress in every window that runs a long step**: a filled progress bar and a line that says what it is
  doing, how many of how many, and the time left once a few items set the pace.
  - **Web scraping, “2 · Search”**: in place of “Searching with 2,540 saved DOIs and 532 saved keywords …”, each phase
    in turn. The keywords show the source and keyword asked now and the new papers so far (*Searching the keywords —
    148 of 2,128 searches · OpenAlex: “LLZO garnet” · 312 new papers so far · about 6 min left*). Then come the
    OpenAlex records of the new papers, the missing abstracts (with how many were found), snowballing and the
    scoring.
  - **Web scraping, “1 · Fetch DOIs”**: the bar fills with the keyword searches (it only moved to and fro). **Re-screen**:
    the papers scored, of how many.
  - **Download and extraction** (web and local): *Downloading — 12 of 40 papers · about 3 min left*; *Extracting — 7 of
    25 PDFs · <file> · about 2 min left*.
  - **Classification, “▶ Classify everything”**: a bar and its four steps (reading the databases, classifying, writing
    one database per class, the classification by property family by family).
  - **Ranking**: a bar beside “Rank” and its steps; the Materials Project entries, composition by composition.
  - The progress never stops a step: a display that fails is ignored.

### Changed

- **The repository in six folders** (from seventeen at its root):
  - `core/`: the pipeline (LocalExtraction, WebScraping, SelectingTopMaterial, Classification, Evaluation);
  - `export/`: MLDataset and Release;
  - `app/`: mme_gui and mme_home;
  - `resources/`: `configs/` (the job files) and `examples/` (the worked example);
  - `docs/`, with the article drafts in `docs/paper/`;
  - `scripts/`.

  The package names, the commands, the installed wheel and the folders of `~/MoukhlijMatExtract` are unchanged.
  From a checkout, run `make install` (or `pip install -e .`) once after updating; a part started from its folder
  is now `python core/LocalExtraction`.
- **README rewritten as an overview for users and reviewers**: the project in one minute, why it exists, one real
  extracted value with its provenance, the pipeline and the extraction engine as diagrams, the 25 search and 17
  copy sources, the ranking, classification and ML datasets, the measured accuracy with its limits, reproducibility,
  the program's windows, install, quick start, the folders, the repository layout, platforms and tests, and an index
  of the documents. The step-by-step guide and every option stay in `docs/MANUAL.md` and `docs/COMMANDS.md`. Links
  to the documents are absolute, so they work on PyPI too.

### Fixed

- **A search started again showed 15 % where it had stopped at 78 %.** Nothing was searched twice (every finished
  search is in the ledger and is skipped), but the bar counted the searches source by source, so it began again at 0
  and reached the first source with searches left (one that had refused them) at 15 %.
  - **Now:** the search counts the searches already finished before it starts, and its bar, its line ("8,820 of
    11,704 searches") and its details window start there. Only the searches asked move it.
  - **The time left:** it is measured on the searches this run asks. Skipped searches no longer make it look fast,
    nor shorten the estimates of the next runs.
- **⏱ Progress details disagreed with its window** (the web window's bar at 80 %, the details window at 0 %). The
  window's bar showed the phase under way by count; the details window measured the time spent against the time left,
  near 0 % for a search started again with hours of searches ahead.
  - **Now:** one number for both, in every window (Web scraping, Local extraction, Ranking, Classification): the work
    done over the work known, each phase weighed by its time per item, the items an earlier run finished counted as
    done. Worked out each time the step says how far it is, so the two views read the very same value.
  - **It never goes back:** a phase whose size is known only when it starts adds work, and the bar waits for it to
    catch up. A stopped step stays where it stopped (it read 100 %). The phase rows of the details window still show
    each phase by count.
- **⏱ Progress details stopped adding to its timeline after 2,000 events** (the number it keeps), which a long or
  resumed search reaches in minutes. The newest events now keep arriving at the top; the oldest go after 2,000.
- **Linux, Windows and small screens** (found with the test runs of GitHub on Linux, Windows and macOS, failing since
  18 November, and checked here as a screenless Linux machine and as a 1024 × 768 screen):
  - **Python 3.11** could not load the ML export, the classification by property or the duplicate detection: one
    f-string used quotes that only Python 3.12 allows (`mme-ml-export --list`).
  - **Windows:** the links to the files of this computer were made as `file://C:\…` (not a link a program reads):
    the extraction did not find an archived paper's PDF where papers.csv said it was, and the benchmark's keyword
    baseline found no PDF. They are made as `file:///C:/…` now, and the old ones are still read
    (`LocalExtraction/fileurls.py`).
  - **Windows:** a command whose output went to a file or a pipe stopped on its first ✓, ≥ or → (cp1252 has none of
    them) — even `mme-eval --help > help.txt`. What such a console cannot show is now shown as “?”.
  - **Windows:** the records of what a run wrote (run_manifest.json, the “done” stamps) held `total\values.csv`; they
    hold `total/values.csv` on every system, so a results folder moved to another computer keeps its records.
  - **Windows:** a title of the Process flow ran past its box (the system's font is wider); it is made smaller to
    fit.
  - **Small screens** (1024 × 768, or a laptop at 150 %: 1280 × 720): the tables were crushed by the settings above
    them — the ranking's table got 3 rows, the web window's values to check 1. The ranking's tables keep half of the
    window, the Local / Web / Classification tabs 62 % of a short window, and the settings scroll; the buttons of the
    Verify tab always stay whole.
  - The tests: the main window's ran without a screen and failed (their “skip without a screen” sat on a helper);
    Windows does not hit-test a fully transparent window, so the tests' hidden windows are 2 % opaque there; a test
    no longer deletes a folder whose file is open on Windows, which Windows forbids.
- **Ranking window**: a ranking that failed left the line under the buttons saying “Reading the databases and ranking
  the materials …” after the error message. It now says the ranking failed, and to press Rank to try again.
- **“⇄ Flow” button**: it chose a free corner when a window opened or was resized, but not when another tab was
  shown, so it could sit over a control of that tab (a scroll bar of the Candidates table). A change of tab looks
  for a free spot again (unless the button was dragged).
- **Ranking window**: its settings were cut off on the right at the size it opens at, not only at its smallest. The
  two frames side by side need about 1,270 px and the window opened at 1,260 (smallest 1,000), so the hints, the
  “Verified values only” box and the folder counts ran past the edge. Now the two check boxes are on lines of their
  own, the counts beside each folder are short (all of them are in the “Rule and data” tab), and the window opens
  at 1,320 px (smallest 1,280, or what the screen can show).
- **Web scraping window**: at its smallest size, “Delete outputs…” was squeezed to a sliver (28 of 124 px). A second
  “☕ Keep the computer awake” switch in the row of the steps took its room; the one in the window's footer stays
  (the same switch, for every window).
- **Make commands window**: in dark mode, the badge of the panel had white text on light blue (hard to read); the
  text is now white or near-black, whichever reads better on the colour.

- **“⚙ Make commands” in the main window**: every `make` command explained, and the flow of the whole project.
  - **Project flow**: a diagram from the setup to the end of every branch. You start with *install → test → demo →
    gui*; then your own PDFs (*local*) or papers from the web (*web-check → doi → web*, later *update* and
    *coverage*) build **your database**. From it you rank, classify and make ML datasets. Measuring the accuracy runs
    *eval-sheet → you annotate → eval-score → eval-benchmark*, with *eval-agree*, *eval-gold* and *eval-reference*.
    Sharing runs *release → Zenodo* and *paper → the article*. Each command is a box, its variants (window, cathode,
    anode …) are chips under it, and the upkeep and `*-help` commands have their own box. Click any of them: the
    panel says what it does and why to use it, lists its options, and gives the command to copy.
  - **Every command**: the same explanations as a list by stage, with a search box.
  - A test checks that every target of the Makefile is explained and drawn, so the window keeps up with the Makefile.

- **`mme-eval benchmark`** (`make eval-benchmark`): MoukhlijMatExtract against other methods, on the same annotated
  papers. It scores MoukhlijMatExtract, a **keyword baseline** and any other tool you give it with
  `--tool NAME=file.csv` (ChemDataExtractor, an LLM prompt …). The baseline reads the same PDFs and takes a number
  with the property's unit from a sentence that names the property. Each system gets precision, recall and F1 with
  95 % intervals, per property, plus the paired difference with MoukhlijMatExtract. Output: `benchmark.md`,
  `benchmark.csv`, `benchmark.png`, `baseline_predictions.csv` and the run manifest, in `Evaluation/benchmark/`.
- **`mme-eval gold`** (`make eval-gold`): the annotated papers as a **public gold-standard dataset**, ready for Zenodo.
  `gold.csv` holds every reference value: correct, partly correct (corrected) and missed. With it come `papers.csv`,
  the annotation guide, the agreement of two annotators (`--second`, Cohen's κ), a datasheet (`README.md`),
  `.zenodo.json` (CC BY 4.0) and `SHA256SUMS`. Sentences are quoted only from openly licensed papers.
- **Duplicate detection: one measurement, counted once** (`LocalExtraction/duplicates.py`). A value repeated in its
  paper, or quoted by a later paper, is traced back to its original. Rows match on the same material (by
  composition), property, component, origin and kind of energy, the same value within the evaluation's tolerances,
  and compatible temperatures. Two papers that report the same value as their own are flagged as “possible”, never
  merged.
  - **The ML datasets and the classification by property** count each measurement once: a repeat or a quote goes to
    `excluded.csv` with why. `values.csv` gains `measurement_id`, `duplicate_kind`, `n_papers_reporting` and
    `original_paper`; `dataset.csv` gains `n_measurements`. To keep them all: `--keep-duplicates`
    (`make ml-export KEEP_DUPLICATES=1`) or the new check box of the window.
  - **A report across databases:** `python -m LocalExtraction.duplicates <folder> … --out <folder>`.
- **`make paper`: every table and figure of the article, made again from the data** (`scripts/reproduce_paper.py`).
  It writes the database summary, the duplicates, two figures (activation energies by component, room-temperature
  conductivities), the ranking, the classification and, once papers are annotated, the scores and the benchmark,
  into `~/MoukhlijMatExtract/paper/`. The seeds are fixed. `environment.json` records the commit, Python, every
  package's version, the hash of `requirements.lock` and the inputs' checksums; `RESULTS.md` says what was made and
  what was skipped. A **Dockerfile** pins the same environment (`make paper-docker`).

- **The program's own name on macOS: “MoukhlijMatExtract” in the Dock, the app switcher (⌘-Tab) and the menu bar**,
  in place of “python3.13” (the program runs inside the Python interpreter, which macOS named it after).
  - **`mme-gui --install-app`** (or `make app`) makes `~/Applications/MoukhlijMatExtract.app`, with the program's
    icon. Opened from it, macOS registers the program as that app: the Dock shows its name and icon. The app holds
    no copy of the program: it runs this Python with this environment, so updating the project updates it. Make it
    again after moving the project or its Python.
  - **Started from a terminal** (`mme-gui`), the menu bar says MoukhlijMatExtract too; the Dock, which reads the name
    only as a program starts, keeps the interpreter's name — open the app for the Dock's.

- **Classification by property: “▶ Classify everything” in one click** (and `mme-classify`).
  - **The flow:** ① every family, crystal (garnet, NASICON …) and chemical (oxide, sulfide …) → ② every property
    alone (activation energy, ionic conductivity, diffusion coefficient, electronic conductivity) → ③ every type
    (bulk, grain boundary, total) → ④ every origin (experimental, simulation) → ⑤ the quality defaults of the ML
    datasets → ⑥ one table per branch.
  - **Where:** `Classification/by_property/<axis>/<family>/<property>/<type>/<origin>/` with `dataset.csv` (one row
    per material) and `values.csv` (every value with its sentence and page); `tree.csv` lists every branch with its
    counts, range and best material; `README.md` shows the tree. A branch no value reaches is not written.
  - **The window:** a first tab, **By property**, shows the tree; a branch selected lists its materials, with
    “Open dataset.csv” and “Open its folder”.
  - **“Classification flow…”** opens a window that draws the flow, step by step, with the numbers of the last
    classification (families, values per property, per type, per origin, branches).

- **“‹ Back to the main window” in every window opened from it.**
  - **Where:** at the left of the header band of Local extraction, Web scraping, Ranking, Classification, ML
    datasets and About & methods; at the bottom, in place of “Close”, of the Requirements guide, the Manual, the
    Results and the CSV files. A window opened from another one says “‹ Back”, and goes back to that one.
  - **Polite while a step runs:** in Web scraping and Local extraction it asks first; going back stops the step,
    keeping what it has finished. Classification and Ranking (seconds, their files written in one go: they cannot be
    stopped half-way) ask nothing: “‹ Going back when it's done …”, then back. Opening Classification starts it at
    once, so a Back pressed right away no longer asks to stop it.
  - **Shortcut:** ⌘[ on macOS, Alt+← elsewhere. A window started on its own (`mme-rank gui` …) has none.

- **5 · ML datasets: datasets ready for machine learning** (`mme-ml-export`, a fifth card in the main window).
  - **The window** asks step by step, each step appearing once the one before is answered: ① the family (a crystal
    structure or structure family of 4 · Classification, or a whole database), ② the property (activation energy,
    ionic or electronic conductivity, diffusion coefficient), ③ the transport component, ④ measured or computed,
    ⑤ the filters (result of, kind of energy, temperature, mobile ion, value range, quality, values per material),
    with the count of what is kept updated as they change, then ⑥ **Generate the dataset for ML**.
  - **The folder** `~/MoukhlijMatExtract/Ready for ML/<name>/`: `dataset.csv` (one row per material: median, log10
    for conductivities and diffusion coefficients, spread, number of values and papers, a group column for grouped
    splits), `values.csv` (every value with its sentence and page), `excluded.csv` (every value left out and why),
    `README.md` (a datasheet) and `settings.json` (to make it again).
  - **The checks by hand apply:** a value marked wrong in the Verify tab is left out, a corrected one is taken as
    corrected, and “only the values checked by hand” keeps those alone.
  - **The command:** `mme-ml-export --family garnet --target Ea --component bulk --origin experimental`;
    `--list` shows the families and their values; `make ml-export`, `make ml-gui`.

- **Springer Nature's two keys, and open Springer, Nature and BMC papers downloaded through its Open Access API.**
  - **API keys…:** the Springer Nature card has two inputs, as the Basic plan gives two keys: the **Meta API key**
    (search and abstracts, `SPRINGER_NATURE_API_KEY`, as before) and the **Open Access API key**
    (`SPRINGER_NATURE_OA_KEY`).
  - **A new source of copies, “Springer Nature (open access)” (`springeroa`):** for a Springer, Nature or BMC paper,
    the Open Access API is asked by DOI; it knows the paper only when it is open. The PDF is then downloaded from
    link.springer.com (whose robots.txt allows it), or, for Nature and BMC, from the article page's PDF link. A
    closed paper is not asked again of anyone for this.
  - **Job files:** `springeroa` follows `wiley` in the sources of copies of every shipped job.
  - **Check setup** says whether the Open Access API key works.

- **“☕ Keep the computer awake”** in every window (the footer of each part, and the main window): a long search,
  download or extraction is no longer stopped by the computer going to sleep.
  - **One switch for the program:** ticked in any window, it is ticked in all of them; it stays on until unticked,
    and goes off when the program ends, even after a crash.
  - **How:** macOS `caffeinate` (display, idle and system sleep), Windows' power request, Linux `systemd-inhibit`.
    The switch is greyed out where the computer offers none.
  - **What it cannot do:** keep a laptop awake with its lid closed (macOS's own rule, unless on power with an
    external display).

- **What each download got, and what it missed: the Downloads tab and `download_log.csv`.**
  - **The record:** every download, from the window or the terminal, adds one line per paper to `download_log.csv`
    in the job's papers folder: time, run, result (downloaded, not downloaded, waiting), title, year, journal,
    where the copy came from or why there is none, what to do, the PDF file and the paper's link. Earlier runs are
    kept.
  - **The Downloads tab** (Web scraping window) shows the last download, filled live while it runs, or **every
    paper tried so far** (from the ledger, for the papers downloaded before the log existed). Totals at the top
    (✓ downloaded, ✗ not downloaded, ⏳ waiting), a filter, a search box, and a double-click that opens the PDF or
    the paper's page. “See every paper of this download” on the card at the end of a download opens it.
  - **The Candidates tab** says why a paper was not downloaded in plain words (“not downloaded (2/3 tries) — site
    refuses programs”) instead of the raw error, which stays in the paper's details.
  - **ⓘ lines** at the top of the Candidates and Downloads tabs say what each shows and how to use it.

- **“Get the rest with my browser…”** in the Web scraping window (and “Get them with my browser…” in the window of
  the papers not downloaded): the papers left on the hand list, fetched with your own browser.
  - **Opening:** the pages open in your usual browser, a batch at a time (10 by default), a moment apart.
  - **Taking in:** the PDFs you save arrive in your Downloads folder (or another you choose). Each is moved into
    `by_hand/` once complete and taken in: DOI read from the PDF, title checked, source recorded as “by hand”.
    The hand list is rewritten without it, and the paper's line reads “taken in”.
  - **Nothing else is touched:** only PDFs that arrive after the window opened and name a DOI of the list are moved.
  - **The next batch by itself:** when every paper of a batch is taken in, left in `by_hand/` or skipped (**Skip**),
    the next batch opens on its own (“open the next batch by itself”, ticked by default). 5 papers a batch by default:
    a person's pace, well below what makes a publisher block a network.
  - **Why a person stays in the loop:** the sites left (MDPI, ACS, RSC, SSRN …) refuse programs. Getting past that
    by disguising a program would break their terms and the program's rule of legal sources only.

- **The project's website** ([moukhlijmatextract.vercel.app](https://moukhlijmatextract.vercel.app)): how to use
  the program, step by step, and an overview of the project.
  - **Main window:** when it opens, a card at its top announces the website, with its link. It closes by itself
    after 7 seconds, or at once with its ✕.
  - **Every window:** the website's address is at the bottom, and a click opens it in the browser. It is in the
    footer of the four parts and of the main window, and on a line under each dialog, table of results, guide and
    details window.
  - **Elsewhere:** in About & methods, in the Requirements guide and in the package's links (`pyproject.toml`).
  - **One place to change it:** `LocalExtraction/about.py` (`WEBSITE`).

- **The program's icon.**
  - **Where it shows:** the Dock on macOS, the taskbar on Windows and the title bar on Linux, for every window, in
    place of Tk's blank icon.
  - **What it is:** the crystal of the windows' header on the band's navy. It ships inside the package
    (`LocalExtraction/gui/assets/mme_icon.png`); `scripts/make_icon.py` draws it again.

- **Citation snowballing** (`search.snowball`, `mme-web run --snowball`, "Follow the citations of the papers kept" in
  Search settings…).
  - **Backward:** the papers kept so far give, through OpenAlex, the papers they cite.
  - **Forward:** they also give the papers citing them, the most cited first, up to `search.snowball_citing`.
  - **Screening:** what is new is screened like any other paper and says how it was found (`snowball: cites W…`).
  - **Repeats:** a paper snowballed is not asked again for 30 days.
  - **Window:** the search shows the step as ③ Citations.
- **Coverage of the corpus** (`mme-web coverage`, **Coverage…** in the Web scraping window, `make coverage`).
  - **By job:** papers found, screened, proposed, downloaded (with the share), left without a legal copy, and
    extracted.
  - **By publisher:** the same counts.
  - **Files:** `WebScraping/coverage/coverage.md` and two CSV tables, ready for an article's limitations.
  - **Safety:** the ledgers are only read.
- **Keeping a database current.**
  - **`mme-web run --update`:** searches only from the year of the job's last search.
  - **`mme-web update`:** does the same for every job run before (`make update`).
  - **Scheduling:** the manual shows how to schedule it monthly.
- **A database against the curated ones** (`mme-eval reference --against <results folder>`).
  - **What is compared:** each room-temperature material of OBELiX and of the Liverpool dataset, met in the
    database from any paper. Your median conductivity is set against theirs.
  - **What it gives:** how many of their materials the database holds, and the share agreeing within 0.1, 0.5 and
    1 decade.
  - **First result:** on a copy of the web database, 84 of OBELiX's 464 materials; 63 % within 0.5 decade, 82 %
    within 1 decade.
- **Materials Project entries beside the ranking** (`mme-rank --materials-project`, or in the Ranking window).
  - **Your own key:** typed hidden in the Ranking window's **Materials Project key** field, saved with **Save the
    key**. It also appears in the Web scraping window's API keys.
  - **What it writes:** `materials_project.csv`, with each ranked material's stability, band gap, space group and
    link.
  - **Matching:** by reduced formula.
  - **The ranking itself:** unchanged.
- **Screening that learns from your decisions.**
  - **Training:** after 10 decisions by hand (3 yes and 3 no at least), a model of them gives each paper still
    waiting its chance of a yes (the `model` column, `model_yes` in `candidates.csv`).
  - **Order:** the review list puts the most uncertain first.
  - **Accuracy:** on your own decisions (5-fold), it is written in the log.
  - **Limits:** it decides nothing.
  - **Who decided:** the ledger records which decisions were a person's (`decided_by`).
- **Crash reports.**
  - **Where:** an error the program did not expect is written to `~/MoukhlijMatExtract/logs/crash_<date>.log`, and
    the message says where.
  - **What it holds:** the version, the command, Python, Tk, the system and the traceback.
  - **Coverage:** every command and every window.
- **A publishing workflow** (`.github/workflows/publish.yml`).
  - **Trigger:** a tag `vX.Y.Z` builds and checks the package (it stops if the tag is not the version), uploads it
    to TestPyPI, then to PyPI once approved.
  - **Before it can upload:** it needs the trusted publisher set on PyPI (docs/PUBLISHING.md § 6).
- **Every shipped job file checked by the tests.**
  - **Loading:** it loads, with queries and words to screen with.
  - **Folders:** its own folders and DOI list.
  - **Queries:** no query twice.
  - **E-mail:** no personal e-mail.
  - **Version:** the version is checked to be the same in `pyproject.toml` and `CITATION.cff`.

- **Every command in one, and its manual.**
  - **`mme`:** `mme help` lists every command, `mme commands` prints every option of every command, and
    `mme <part> …` runs a part (`mme local`, `mme web run`, `mme rank`, `mme eval score` …). It is installed with
    the package, so a copy without the project folder has every command.
  - **`docs/COMMANDS.md`:** every command with all of its options, written from each command's own `--help`
    (`make commands`).
  - **`docs/MANUAL.md`:** the complete manual for users and reviewers. It covers installing, the three domains,
    every step, the outputs, measuring the accuracy, reproducing a result and the legal sources.
  - **New make options and targets:** `DOMAIN=`, `KIND=`, `ALL_PAPERS=`; `make web-cathode`, `web-anode`,
    `rank-cathode`, `rank-anode`, `local-cathode`, `local-anode`, `commands`, `manual`, `mme-help`.
  - **Tests** check that every option of every command can be given through its make target, and that the
    reference and the manual name only what exists.

- **Three domains: electrolytes, cathodes and anodes.** Each has its own job file, ranking criteria and database.
  - **Job files:** `configs/sse.yaml`, `configs/cathode.yaml`, `configs/anode.yaml`. Each has its own search, download
    folder and DOI list. The cathode and anode starters ship with the package and are made next to `sse.yaml` on the
    first run.
  - **`extract.domain`** in a job file, and `mme-local --domain`: what the database is about, recorded in the run
    manifest. A cathode database keeps cathodes and flags solid electrolytes, interphase salts, alloys and
    lithiated carbon. An anode database keeps alloys, carbons, titanates and conversion oxides, and flags solid
    electrolytes and interphase salts.
  - **`mme-rank --domain cathode | anode`** ranks with `criteria_cathode.toml` / `criteria_anode.toml`: low, moderate
    and high barrier. Their limits are starting points to set for a study.
  - The electrode jobs also extract capacity, capacity retention, voltage and rate capability.

- **`energy_kind`** in the activation-energy table: what kind of energy each "activation energy" is.
  - The kinds: `arrhenius` (the slope of long-range transport: impedance, molecular dynamics, PFG-NMR),
    `migration_barrier` (a static barrier of one hop: NEB), `bvse`, `local_hop` (NMR relaxation, QENS), `vtf`,
    or no ion migration at all (`rotation`, `charge_transfer`, `electron_transfer`), else `unspecified`.
  - It is read from the value's own clause first, then from the method named just before it or the one method
    of the paper. `basis` says which (`kind: stated (NEB)`, `kind: assumed (…)`).
  - Papers give one name to all of these, and they are different quantities: a static barrier leaves out the
    defect formation energy and is lower than the Arrhenius activation energy of the same material
    (`LocalExtraction/energy.py`).
  - `mme-rank --kind arrhenius` ranks one kind only.
  - A database of an earlier version gets the column, from each row's own sentence, when it is brought up to date.
- **Activation energies of something other than ion migration are flagged** (`plausibility: check: …`), so the
  ranking leaves them out by default:
  - anion rotations (marked before, but still ranked);
  - the exchange current or charge transfer at an interface, and ion transfer across one ("through the
    interface", "the PEO|LATP interface", "the SEI and CT processes");
  - electron transfer;
  - reactions ("the nucleation activation energy", "the activation energy of crystallization").
- **Values of materials that are no candidate electrolyte are flagged** (`LocalExtraction/scope.py`); the ranking
  leaves them out by default (`--include-flagged` brings them back):
  - interphase compounds and simple salts (LiF, Li2CO3, CaO …);
  - alloys and lithiated carbon;
  - transition-metal electrode materials (LiCoO2, LiFePO4, Li3V2(PO4)3 …);
  - molecules (H2O);
  - composites with a polymer, a gel or a framework, when the value's own clause says so;
  - doped samples stored under the undoped formula ("the Al-doped LLZO" as Li7La3Zr2O12).
- **Cs+ and Rb+** are recognised as mobile ions.
- `docs/LIMITATIONS.md` § 2 gives a first measurement of the precision of the activation energies on papers that
  were not used to write the rules (37–41 % fully correct, 57–62 % counting doubtful cases), and what limits it.
- **Papers to download by hand.**
  - **The list:** every download lists the papers it could not get in `to_download_by_hand.csv` (papers folder),
    with the link, the reason and what to do.
  - **The window:** a window shows the same list (*Papers not downloaded automatically*), and the result card
    reopens it.
  - **The intake:** a PDF saved from the link into `by_hand/` is taken in by the next download — matched by DOI and
    title — with its source recorded.
- **Sites that refuse programs:** a site that answers HTTP 403 three times in a row is not asked again in the run,
  and its papers lose no try. Redirectors (`doi.org`) are never blocked.
- **`configs/garnet_nasicon.yaml`:** a job for garnet and NASICON solid electrolytes only.
- **`docs/EVALUATION_PROTOCOL.md`:** the held-out evaluation for the garnet/NASICON study, written before the draw.
  `scripts/audit/heldout_source.py` makes the copy of a database without the papers already used.
- **`docs/MANUAL.md` § 12:** the environment variables the commands read.

- **Checking the values by hand — the Verify tab** (windows 1 and 2):
  - **What it shows:** each activation energy beside the page of the PDF it was read from, its sentence marked.
  - **The order:** the values the Arrhenius cross-check disputes first, then those the extraction flagged, then
    the lowest energies.
  - **Verdicts:** correct (c), wrong (w), or corrected (e: material, number, kind, component, origin,
    attribution), with an undo.
  - **Where they are kept:** `~/MoukhlijMatExtract/Verification/<database>.csv` (`LocalExtraction/verification.py`),
    outside the database, so a rebuild never loses them.
  - **In the ranking:** a value marked wrong takes no part, a corrected one takes part as corrected, and
    `--verified-only` (the window's "Verified values only") ranks the checked values alone. The checks are part of
    the ranking's fingerprint.
- **The windows show what a reader needs to judge a value:**
  - **The Activation energies tab:** each value's kind of energy, component, origin, attribution, mobile ion,
    confidence, the extraction's flag ("look at it?", in orange), the hand check and the Arrhenius result. The
    line above counts the values to look at, those checked by hand and those the Arrhenius check disputes.
    Double-clicking a row shows everything about it.
  - **The card of an extraction:** says how many new values need a look, which kinds of energy were found, and
    goes on to the Verify tab.
  - **The main window:** each database's line says how many of its values were checked by hand.
- **The Arrhenius cross-check** (`LocalExtraction/arrhenius.py`):
  - **What it does:** a paper's conductivities at several temperatures give an activation energy (ln σT and ln σ
    fits). It is compared with the value the paper reports.
  - **When it is uncertain:** cited values, room temperature alone, and conductivities that fall with temperature
    are left unchecked.
  - **Where it shows:** "Arrhenius fit disagrees" among a material's checks, `arrhenius_check` beside each value,
    and `python -m LocalExtraction.arrhenius <database>`.
  - **On the current web database:** 11 values checkable, 6 inconsistent — among them a NASICON value read as
    2.4 eV where its paper's conductivities give 0.30 eV.
- **How sure each rank is:**
  - **Rank intervals:** 1,000 resamplings of every material's values (fixed seed; `--bootstrap N`) give
    `rank_95`, the 95 % interval of each rank, and `p_top10`, the share of resamplings that put it in the top 10.
  - **Evidence tier:** A (3 values or more from 2 papers or more), B (2 values or more) or C (a single value).
  - **Where they show:** in every table, the report and the window, and on the card ("5 of the first 10 stay in
    the top 10 in 90 % of the resamplings").

### Fixed

- **Ctrl-C in the terminal froze a window that was running a step.** The window closed at once, but the step (a
  search, a download, an extraction) was never told to stop: its threads went on working with no window, and the
  program never ended. Now Ctrl-C (or SIGTERM, or the terminal closed) presses Stop on every running step, says to
  wait while it saves, keeps the window until the step has ended, says it stopped cleanly, then closes. A second
  Ctrl-C quits at once. With nothing running, the window closes at once, as before.

- **Six bugs found in a review of the newest features.**
  - **ML datasets:** a dataset name typed with `../` could write outside `Ready for ML/` (now kept inside); two
    spellings of one material from a whole database were two materials (now merged by composition, as
    Classification does); changing an earlier step while the count was being updated could crash the window.
  - **Downloads tab:** a line of `download_log.csv` still being written could show as a broken row; the log was read
    again at each key typed in the Candidates filter.
  - **Browser helper:** a new PDF whose browser kept the server's date was ignored, and the PDFs already in a folder
    chosen with “Change…” were taken for new ones. Watching now starts from a snapshot of the folder's names.
  - **Keep awake (Linux):** after a crash or a kill, the sleep lock stayed until the computer restarted; it now ends
    with the program, as on macOS.
  - **Stopping from the terminal:** “Stopped cleanly” was said after “Quitting at once”.
  - **Springer Nature:** its daily quota used up held its papers in the rounds at the end of a download; they are now
    filed and asked again by the next download.

- **A crash, “KeyError: 'popdown'”, when the mouse wheel turned over the open list of a dropdown** (the ML datasets
  window, and any window whose controls scroll). The open list is a window Tk makes itself, with no Python widget
  behind it; the scrolling area now asks by window name, and the wheel scrolls the list.

- **OSTI held hundreds of papers it could never have had.**
  - **The cause:** OSTI (the US Department of Energy's repository) was asked about every paper; it ran into its
    limits, and every later paper was marked “refused by OSTI” and waited for the end of the download.
  - **Now:** OSTI is asked only about papers OpenAlex ties to the US DOE: a DOE funder or one of its offices (Office
    of Science, Basic Energy Sciences, EERE, ARPA-E …), or an author at a DOE national laboratory. A paper OpenAlex
    does not know is still asked, rather than a DOE paper missed. Of 25 papers that waited on OSTI, none was tied to
    the DOE; the three papers OSTI had supplied all are.

- **Stopping from the terminal says what happens.** Every stop signal — Ctrl-C, `kill` (SIGTERM), the terminal
  closed (SIGHUP), Ctrl-Break — shows a box: please wait, the work is being saved and finished; then a box when it
  has stopped cleanly. A second signal quits at once, said too.
  - **Long commands** (`mme-local`, `mme-web`, `mme-eval`, `mme-dois`) stop after the item under way, saving what
    is finished, as Stop does in the window.
  - **Short commands** (`mme-rank`, `mme-classify`, `mme-release`) finish and save first, then stop.

- **A download spent a day retrying papers Semantic Scholar had refused.**
  - **The cause:** after three “too many requests” (HTTP 429), the download stops asking Semantic Scholar for the
    run. Every later paper without a copy was then marked “waiting: refused by Semantic Scholar” and retried at the
    end, one after another, up to 30 s apart, in four rounds: 900 papers took about 7.5 hours a round.
  - **What Semantic Scholar adds:** an arXiv version or a repository copy, which the other services mostly know
    already. Of 30 such papers, 2 had a green copy and none an arXiv version.
  - **Now:** a paper only Semantic Scholar refused is filed with what the other services answered. It goes on
    `to_download_by_hand.csv` with its real reason, the try does not count, and the next download asks again.
    A paper another service refused too still waits for the rounds.
  - **A budget per round:** a round at the end takes at most 30 minutes of spacing, the least-tried papers first.
    The others stay on the watch list for the next “3 · Download”, which says so.

- **The download stopped before its first paper** with `field larger than field limit (131072)`.
  - **The cause:** some repository records (Zenodo, DataCite) give a whole text as their abstract: up to 465,682
    characters. The review list (`candidates.csv`) then held cells Python's CSV reader refuses, and reading it is
    the download's first step.
  - **Reading:** the program now reads cells of any length, everywhere it reads a CSV file.
  - **Writing:** the review list shows the first 10,000 characters of an abstract, marked as cut. The ledger keeps
    every character, and screening reads them all.
- **Python no longer quits unexpectedly when a window is stopped.**
  - **The trigger:** Ctrl-C in the terminal, closing the terminal, or a request to stop (SIGTERM) while a window was
    open.
  - **The crash:** Tk's signal handler shut the window down from whatever thread the signal reached, and Python
    stopped with a fatal error (macOS: "Python quit unexpectedly").
  - **Measured:** 9 times out of 10 with a step running.
  - **Now:** the window's loop ends and the window is closed cleanly; 10 times out of 10 measured.
- **A scrolling area no longer loops.**
  - **Window size:** in a window sized by its content, the scroll bar appeared, the window grew, the bar went, the
    window shrank, without end. The window never settled, and Tk ran out of stack and crashed.
  - **Wrapped text:** the bar narrowed the content, text wrapped onto more lines and the bar stayed; without the bar
    the text took fewer lines and the bar went, without end. The window froze. The content now keeps its width
    whether the bar shows or not.
  - **Closing:** a resize Tk delivered while a window closed no longer raises an error ("Something went wrong").
- **The test suite no longer crashes Python under Tk 9** (Homebrew's Python).
  - **The cause:** checking for a screen made a window and destroyed it at once. Tk 9 was left a "show it" step for
    a window that was gone, and the next window of the run crashed Python.
  - **Now:** the check is made once, safely, and every test's window finishes Tk's pending work before it is
    destroyed.
- **The API keys are kept in `~/MoukhlijMatExtract/.env`.**
  - **The problem:** they were inside the installed package, where `pip install --upgrade` deleted them, and where
    a Python installed for every user could not save them.
  - **Carried over:** keys saved by an earlier version are copied there once, readable by their owner only; the old
    file is left as it was.
  - **The tests:** they never read a person's keys.
- **Ranking and Classification check the main folder first.** A step started after `~/MoukhlijMatExtract` was
  deleted asks to make it again, as the extraction windows do. Before, the ranking failed to write its files, and the
  classification read from a folder that was gone.
- **Windows that fit any screen, with areas to resize.**
  - **Size:** every window and dialog opens sized for the screen it is on: larger on a large screen, never beyond
    what the menu bar and the dock or taskbar leave, with a minimum the screen can hold. A main window opens centred;
    a dialog opens over the window it belongs to.
  - **Lines to drag:** the controls and the tabs (Local extraction, Web scraping, Classification); the ranking's two
    columns of settings; the Verify tab's details and page. A line dragged by hand stays where it was put.
  - **Scrolling:** controls that do not fit scroll, with the mouse wheel or a bar that shows only when needed; the
    main window does the same.
  - **Ranking:** its file buttons have a line of their own, so a narrow window no longer cuts "Open the report"
    and "Open the workbook".
  - **Tests:** the window tests now check that a control is really drawn in view, not merely laid out.
- **No personal e-mail in a shipped job file:** `configs/garnet_nasicon.yaml` carried a contact e-mail. Every user
  would have sent their OpenAlex, Crossref and Unpaywall requests under it. A test now checks each shipped job
  file.
- **Two materials of one table are two values to check.** A value is now known by its paper, page, sentence, number
  and material. Before, the rows of a table share its caption as their sentence, so two materials with the same
  energy shared one check: marking one wrong also left the other out of the ranking, and the Verify tab listed
  only one of them (17 of 915 values were hidden on a real database). No check made before is affected: the
  identity changes only for values that were checked by hand.
- **The Verify tab in a small window:** the counts line has a line of its own (beside the filters it wrapped into
  a column one letter wide that pushed the list out of view); the list and the page share the width; the buttons
  keep their room when the window is short. The Web scraping window's minimum size is now 960 × 760, so the tabs
  under the step buttons are never left without room.
- **The Ranking window in a short window:** a divider separates the settings and the card of the last ranking from
  the ranked materials. The tables keep half the height, and the Rank button stays in view. At 1000 × 640 the
  table had no room left.
- **Classification:** the buttons have a line of their own and the database boxes wrap four to a line, so a
  database per job file no longer pushes "Open the results folder" out of the window.
- **The main window:** each part's description wraps to the room it has, rather than being cut at the card's
  edge. The smallest size holds all four cards and the footer, as far as the screen allows.
- **A file that is not a PDF** (an HTML page saved as `.pdf`, a download cut short at its start) is reported as
  "it does not open as a PDF — the file is damaged or is not a PDF; download it again" instead of PyMuPDF's
  internal message.
- **About & methods** states the exact rule for a PDF that is not the paper (two pages or 1,500 characters at
  least; the title in the first three pages when the text has 800 characters or more; scans are not checked).
- **README:** the first start is described as it happens. The main window offers to make the folder; a terminal
  command makes it on its own.
- **Fetch DOIs:** a job's extra keywords are anchored on its main topic only when most of its queries are about it.
  The garnet/NASICON job no longer appends "garnet" to every NASICON keyword.
- **One DOI list per job:** `mme-dois --job X` saves into X's `doi_list`, and `mme-web run --dois` reads it.
  Before, both used the shared `dois.csv`, so two jobs' DOIs mixed.
- **A job file named on the command line** (`--job configs/my_job.yaml`) is found in the folder the command was
  started from when it is not in `~/MoukhlijMatExtract`.
- **No waiting on services that are down:** a paper refused only by services that did not answer at all is left
  for the next run. Before, the watcher's rounds waited up to 32 minutes for it.
- **The same papers give the same files:** tables and `database.json` are written in paper order, not in the order
  the workers finished the papers, so a release's checksums can be reproduced.
- **The tracked job files** no longer carry a personal e-mail (the window's `MME_EMAIL` is used).
- **One database per job:** without `--output`, `mme-web` and the Web scraping window extract a job's papers into
  the job's own results folder, beside its PDF folder: `WebScraping/web_output` for `WebScraping/papers`,
  `WebScraping/web_output_<name>` for `WebScraping/papers_<name>`. Before, every job went into
  `WebScraping/web_output`, so a second job's papers were added to the first job's database. A folder chosen by hand,
  or with `--output`, is kept.
- **The windows (full review of the GUI):**
  - **Papers saved by hand:** “3 · Download” now runs when the only work left is a PDF in the `by_hand` folder.
    Before, it said "nothing to download" and never took the PDF in. The card counts the PDFs taken in.
  - **Rankings and classes written from a window are recorded** like those of `mme-rank` and `mme-classify`:
    `.mme_done.json` and `run_manifest.json`. Before, a command run with the settings of an earlier ranking said
    "Already ranked — skipped" over the files a window had rewritten with other filters.
  - **The ranking window has the filters of `mme-rank`:** the kind of energy (`--kind`), the flagged values
    (`--include-flagged`) and the classes of a domain (`--domain`). It can now make the ranking of the screening
    (experimental, own work, Arrhenius values).
  - **Evaluate…:** each results folder has its own workbook and scores. A job's database
    (`web_output_<name>`) uses `annotation_web_<name>.xlsx` and `scores_web_<name>/`. Before, the scores of one
    database were shown, and could be scored again, as those of another.
  - **Search settings:** “Reset to defaults” keeps the job's name, PDF folder, DOI list and domain. Before, it
    put back the default job's, so a saved reset made the job share the default DOI list. The form shows the job's
    own PDF folder, not the default one.
  - **Delete outputs…** in the Web scraping window offers the job's own DOI list, PDF folder and results folder.
  - The ranking and classification windows offer the other jobs' databases (`WebScraping/web_output_<name>`)
    without ticking them.
  - The list of papers to get by hand is among the window's CSV files. No message box opens when every paper a
    download missed was got on a later round.
  - **Papers refused for too many requests (HTTP 429)** are now tried again at the end of the download one
    after another, spaced by the slowest pace a service asked for (Semantic Scholar: 30 s), instead of in
    parallel. A line of the Web scraping window says how many wait, which services refused them, the pace they
    asked for and the round. The line stays on the download's card, and what is still refused is left for the
    next download.
  - **Re-screen with the settings…** (the Candidates tab) and `mme-web run --rescreen` decide again the papers
    screened before and not downloaded yet, with the job's settings of now. Before, a setting changed after a
    search ("Also keep papers no free copy is known for", a word) applied only to papers found later.
    `configs/garnet_nasicon.yaml` now keeps the papers no free copy is known for (`propose_closed: true`).
  - **Screening finds a formula however a title writes it:** with spaces (`Li 7 La 3 Zr 2 O 12`, as Crossref gives
    sub-scripted titles), with subscript digits (`Li₇La₃Zr₂O₁₂`) or with `<sub>` tags. A part of a formula
    (`La3Zr2O12`, `Si2PO12`) also finds the doped members of its family (`Li6.4Ga0.2La3Zr2O12`). Formula words keep
    their case. Other words match exactly as before (checked on 53,618 papers: no difference). Screening is about 7
    times faster, which a re-screen of tens of thousands of papers needs.
  - **`configs/garnet_nasicon.yaml`:** 60 more garnet and NASICON topic words (LLZ, LLZNO, LALZO, LGLZO, LZP, LCZP,
    LAGTP, the names with British spellings, doped formulas and the parts of each family's formula). Measured on the
    47,845 papers of the garnet/NASICON ledger (a copy): a re-screen alone proposes 720 more papers (screened before
    with an older word list), the formula matching 35 more, the new words 25 more, and `propose_closed` 2,127 more.
  - **`configs/garnet_nasicon.yaml`, more searches:** 86 more queries (304 in all): the other garnets (Ta, Nb, Te,
    Hf, Sn and alkaline-earth members), each dopant of LLZO and the cubic phase, processing that changes transport,
    stability in air (Li+/H+ exchange, Li2CO3), the NASICON sodium dopants and Na-rich phases, the lithium members
    other than LATP and LAGP, the crystal chemistry of NASICON transport, and the methods used on both families
    (NMR, muon spin relaxation, tracer diffusion, BVSE, neutron diffraction). Four more formula parts for the
    screening (La3Zr1, Te2O12, Zr2Si, Ge2(PO4)3): 9 more papers proposed on the same ledger.
  - **One job per family of solid electrolytes:**
    - The 12 families: garnet, NASICON, LISICON / thio-LISICON, LGPS-type, argyrodite, thiophosphate glasses and
      glass-ceramics, perovskite (LLTO), anti-perovskite, halide / oxyhalide, complex hydride / closo-borate,
      β-alumina, and LiPON / oxide glasses.
    - Each family has its own queries (86–273: hand-written ones about its chemistry, and each of its main names with
      every transport measurement and method), its own topic words (names, abbreviations, formulas and the parts of
      formulas that find the doped members), and exclusion words for its usual noise (halide-perovskite solar cells,
      hydrogen storage, mineral garnets, …).
    - Each family has its own DOI list, PDF folder and database.
    - They ship in `WebScraping/averageScrap/families/` and are copied into `~/MoukhlijMatExtract/configs/` when
      missing. `scripts/families/make_family_jobs.py` writes them from one description per family.
    - `configs/garnet_nasicon.yaml` now holds every garnet and NASICON query: 532.
    - **Eight more families** (20 in all):
      - `nitride` (Li3N, nitridophosphates, nitridosilicates, amides and imides);
      - `fluoride` (Li/Na fluorides, oxyfluorides, the fluoride-ion conductors);
      - `mixed_anion` (oxysulfides, sulfide-halides such as Li7P2S8I, nitride-halides);
      - `oxide_chemistry` (niobates, tantalates, zirconates, aluminates, borates, silicates, germanates, tungstates,
        molybdates);
      - `oxide_structure` (spinel, pyrochlore, scheelite, brownmillerite, olivine-related);
      - `polymer` (PEO and other polyethers, polycarbonates, gels, single-ion and block-copolymer electrolytes);
      - `hybrid` (polymer-ceramic composites, MOF, COF, plastic crystals, ionogels);
      - `multivalent` (Mg²⁺, Ca²⁺, Zn²⁺, Al³⁺, Sc³⁺ conductors).
    - **Each family job also asks for:**
      - the older names of fast ion conduction ("fast ion conductor", "superionic conductor");
      - the transport mechanisms (concerted migration, vacancy and interstitial mechanisms, paddle-wheel, percolation,
        bottleneck size), with matching property words.
    - **Each job states its kind**, so crystal-structure types, chemical families, composition systems, material
      classes and mobile-ion groupings stay apart. It also states its prototype and space groups.
      `docs/FAMILIES.md` lists them all.
    - **Screening:** a formula word is no longer found inside another element. `Li3N` does not match `Li3NbO4`.
      Spaces before a word are kept when formulas are joined back together. On the garnet/NASICON ledger, one paper
      fewer is proposed.
    - **`configs/` and `docs/` in the user's folder.**
      - The repository's `configs/` (all 16 job files) and `docs/` (the user's documents) are the only copies.
        The build copies them into the package (`setup.py`, `MANIFEST.in`), and the duplicate `default_*_job.yaml`
        files and the `families/` folder are gone.
      - On start, every command and window copies them into `~/MoukhlijMatExtract/configs` and
        `~/MoukhlijMatExtract/docs`. A job file is made only when missing, never written over; a document is brought
        up to date. `docs/PUBLISHING.md`, for the maintainer, is not copied.
    - **The main window looks after that folder:**
      - A line under “Create / Open the main results folder” says what is missing, if anything: the folder, job
        files, documents.
      - **Restore the job files** makes them again; a job file you edited is kept.
      - **Open the documents** opens `docs/`.
      - At start, and before a part opens, a small window warns when the folder or its job files are missing, and
        offers to make them. Answering “No” leaves the part closed.
    - **`~/MoukhlijMatExtract` deleted while a window is open:** the next step of the Web scraping or Local extraction
      window says so and offers to make it again (the folders, job files and documents), then goes on in it. The web
      window opens a new ledger there. Before, the step worked on in the deleted folder, and its ledger was lost.
    - **`make` keeps the developer's `.venv` up to date:** when `pyproject.toml` or `setup.py` changes (a new part),
      the next `make gui`, `make web`, … registers the package again (`pip install --no-deps -e .`, nothing
      downloaded), so `mme-gui` keeps working from any folder.
    - **A fresh install gets every job file:** “Create the main results folder” (hub), the Web scraping window,
      `mme-web` and `mme-dois` all make `~/MoukhlijMatExtract/configs/` with every shipped job. A shipped job named
      before it exists (`mme-web run --job configs/halide.yaml`) is made first, and is extracted into its own
      `web_output_halide`.
  - **A new look for every window:**
    - a header band with the program's emblem (a crystal unit cell), the window's title, what it does and the version;
    - bordered cards with a status line for each part in the hub ("database: 647 papers, …");
    - striped tables with bold headings;
    - a footer that states what the program commits to (legal sources only, each value traced to its sentence and
      page, each run recorded).
  - **About & methods** (hub, every window and their footer) shows, from the program itself:
    - the version, the commit and the licence;
    - how to cite it (from `CITATION.cff`, with BibTeX);
    - the method step by step, and the rules on sources and records;
    - the accuracy measured on this computer, from the evaluations scored here (with their 95 % intervals), and
      "not measured yet" when there are none;
    - the environment, as a run records it, with a button to copy it for a Methods section.
  - **The Activity tab holds every line of a step:** what the engine logs while a step of the window runs (Fetch
    DOIs, the search, the download, the extraction) is shown there as well as in the strip at the bottom.

- `make help` no longer lists options `mme-eval reference` does not have (`ESTIMATE=`, `GOLD=`, `PDFS=`, `OUT=`).
- `mme-local gui --domain` is passed to the window's extraction.

The fixes below come from a hand check of 60 random activation energies of the legal web database
(November 2026). 14 of its 23 errors are fixed. On 30 other papers, extracted with the old and the new code,
one row of 123 changed, for the better.
- **Measured vs computed:**
  - A measured value quoted in a sentence about a computed one ("The calculated E_a of 0.27 eV agrees with
    the 0.28 eV derived from impedance measurements") is now experimental: a value inside a comparison takes
    its origin from the comparison when that names a method.
  - "Calculated to be" and "calculated as" no longer make a value computed; discs count as specimens.
- **Previous work:** "previous AIMD", "previous predictions" and "previously calculated" now mark a value as cited.
- **Which material a value is for:**
  - A material named only to compare with ("compared with the result of Li10SnP2S12") no longer takes the
    paper's own value.
  - A citation right after a value closes its statement: in a table run into text, the next row's material
    no longer takes the value before it ("… Ea ~ 0.35 eV [17] Li6.5La3Zr1.75Te0.25O12 …").
  - The Kröger–Vink symbol of a vacancy ("VLi", "VNa") is no longer read as a formula ("LiV").
- **Surface values:** a computed value whose sentence names only a surface (or only a grain boundary) is given
  that component instead of the bulk.
- **Numbers that are not results are dropped:** the spread of a distribution ("σ ≈ 0.69 eV"), a discrepancy, and
  the bounds of a prior ("p(Ea) ∼ U(0, 0.5 eV)").
- **More comparisons are recognised** ("compares favourably with … the LLZO garnet", "lower than typical values
  reported for undoped LLZO"), so the material compared with no longer takes the value.
- **Formulas:**
  - Square brackets inside a formula are read ("Li6.5[P0.25Si0.25Ge0.25Sb0.25]S5I").
  - A formula split by a space is joined ("Li1.3 Ga0.3Ti1.7(PO4)3", "Li1.3Ga0.3Ti1.7 (PO4)3").
  - The inside of a formula that cannot be read whole ("SeO3" of "LiM(SeO3)2") is no longer taken for a material.
- **NMR relaxation** ("SLR rates", "spin-lattice", relaxometry) counts as a measurement; a value given for "X = Cl,
  Br" no longer falls back on the paragraph's material.

## [1.1.0]

### Added

- **Tables printed without ruling lines** — most journals' — are read: found under their "Table N" caption,
  their columns from the alignment of the text (`LocalExtraction/tables.py`), a header on two lines joined.
  On 120 random papers of the web database the values read from tables went from 13 to 62. The text of a
  table is no longer read again as sentences, where its cells ran together. Units in square brackets or
  after a slash ("σ [S cm−1]", "Ea / eV"), a subscript put after the unit ("E (eV) a"), and a column of
  materials headed "Samples", "Nominal composition", "Chemical formula" … are read; a formula a cell spaces
  out ("(Li 0.375 Sr 0.4375)(Ta0.75Zr0.25)O 3-δ") is put together.
- **`needs_check`** in every quantity table: "no", or "yes: <reasons>" — out of range, unusual formula,
  doped sample, material from another sentence, table text, low confidence — for the values most worth a
  person's look (`LocalExtraction/review.py`). A database of an earlier version gets the column when it is
  brought up to date; nothing is extracted again.
- **Evaluate…** in the Local extraction and Web scraping windows, next to the extraction: the three steps of
  `mme-eval` on that window's results — make the workbook (papers drawn at random), check the values (the
  user's part), compute precision, recall and F1 — with the last scores shown when it opens, and a re-score of
  a newer extraction against the same checks. `mme-eval sheet` / `score` and the window share
  `Evaluation/steps.py`, so they give the same numbers.
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
- **mme-eval score --predictions** (`PREDICTIONS=`): other tools' values (ChemDataExtractor, …) for
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

- **Web scraping uses open sources only.** The web window searches, reviews, downloads the legal
  open-access copies and extracts them; the **2 · Web scraping** button opens it directly. The DOI collector
  (Fetch DOIs, `mme-dois`, `make doi`), which asks only open indexes (OpenAlex, Crossref, Semantic Scholar,
  arXiv), is its **1 · Fetch DOIs** step. The `[scrape]` extra and the need for Google Chrome are gone.
- **License: GNU AGPL-3.0-or-later** (was MIT). MoukhlijMatExtract reads PDFs with PyMuPDF, which is
  licensed under the AGPL-3.0; a program built on it must be shared under the same terms, so the MIT label
  did not hold. `LICENSE`, `pyproject.toml`, `CITATION.cff`, `.zenodo.json`, the README and the windows say so.

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

- **A material named in a role that is never the measured sample took the value next to it**: the electrode
  of a battery ("NCA//Li", "a LiFePO4 full cell"), a reagent ("NaH2PO4 as a new phosphate source"), the salt
  of a CMC or chitosan electrolyte, a group of a longer name ("TpPa-SO3Li" read as LiSO3). Such a value is
  now kept without a material.
- **Rows of a series table whose formula could not be worked out** ("LATP-xSn (x = 0–0.4)") all took the one
  formula of the caption, and the rows of a table of fillers took the filler's: they are left without one.
- **The hydrogen count of a hydride** ("Li3BN2H8", "Li4BN3H10") was cut off as if it were a citation number.
- **A multiplication sign lost by the PDF made a value up to 9 times too small.** Some publishers' fonts give
  "×" as an invisible control character, or as nothing at all: "1.15 × 10−4 S/cm" was read as 10−4 S/cm. The
  sign is put back between a number and its power of ten (70 conductivities of the web database were
  affected; extract again to correct them).
- **Formulas with fractions of two digits** ("Li3/8Sr7/16Ta3/4Hf1/4O3") were cut short ("Sr7Li0.375"); they are
  read whole.
- **A table column that names the series variable in brackets** ("Content of Sr (x)") now gives each row its
  member of the caption's series (Li6.8La2.95Sr0.05Zr1.75Ta0.25O12 for x = 0.05), not the general formula.

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
  for next time), and points to the optional **API keys**.
  Its steps open only once an e-mail is given.

### Fixed
- The job file shipped with the package carried the author's e-mail, which was sent to OpenAlex,
  Crossref and Unpaywall in place of the user's own. It now ships empty, so the user's e-mail is used.
- OpenAlex now asks for an API key to go past the first page of a search. Without one, `mme-web`
  crashed after its first query and `mme-dois` got no DOIs from OpenAlex; both now take the first
  100 results of each search, and the API keys window says what a free OpenAlex key adds.
- The Classification window no longer shows a message box when it is opened before any database
  exists; it says to run part 1 or 2 first.

## [1.0.0] — 2026-10-25

First public release.

### Added
- **Part 1 · LocalExtraction** — extract structured data from your own PDFs (text, tables, figures,
  equations, OCR) into a database of linked CSVs, an Excel workbook and JSON. No data cell is left
  empty: every value carries a `basis` saying whether it was stated, inferred or assumed.
- **Part 2 · WebScraping** — search 14 open sources (OpenAlex, arXiv, Crossref, Semantic Scholar, …),
  screen, fetch the legal copies and extract them; *Fetch_DOIs* collects a topic's DOIs.
- **Part 3 · SelectingTopMaterial** — rank the materials by activation energy into Superionic /
  Performant / Acceptable / Rejected classes.
- **Part 4 · Classification** — sort the materials by crystal family and structure family, one
  database per class (with bulk / grain-boundary / total sub-classes).
- **One GUI** (`mme-gui` / `python -m mme_gui`) — a hub window with a button for each part.
- Installable package (`pip install .`) with the `mme-gui`, `mme-local`, `mme-web`, `mme-rank`,
  `mme-classify` and `mme-dois` commands; `make` shortcuts; and a test suite run by `make test`.

[1.0.0]: https://github.com/YounesMoukhlij/MoukhlijMatExtract/releases/tag/v1.0.0
