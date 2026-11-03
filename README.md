# MoukhlijMatExtract (MME)

> Extract · Rank · Classify — solid-state electrolyte data from the scientific literature.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://pypi.org/project/moukhlijmatextract/)
[![PyPI](https://img.shields.io/pypi/v/moukhlijmatextract)](https://pypi.org/project/moukhlijmatextract/)

## About the project

**MoukhlijMatExtract (MME)** is an open-source research tool for mining the scientific literature on
**solid-state electrolytes**. Thousands of papers report how fast ions move through a solid — but each in
its own words, units and table layout, so comparing materials across the literature by hand takes weeks.
MME does that work automatically and keeps it traceable.

It reads papers — your own PDFs, or articles it finds and retrieves online from open sources — and
extracts their **ion-transport data** into a structured database:

- **activation energies**, **ionic and electronic conductivities** and **diffusion coefficients**,
  converted to common units;
- the **material** each value belongs to, the temperature, the measurement or simulation method, and
  whether the value is the paper's own result or one it cites;
- the **source of every value** — paper, page, table, figure or sentence — so any number can be checked.

The materials are then **ranked by activation energy** (Superionic, Performant, Acceptable, Rejected)
and **classified** by crystal-structure type (NASICON, garnet, argyrodite, LGPS, perovskite, …) and by
structure family (oxide, sulfide, halide, …), to support the data-driven screening of candidate
electrolytes.

MME works from a window (no command line needed) or from the terminal, keeps all your files in one
folder, never redoes work already done, and never deletes your input PDFs.

### How it works

MME has four parts. Parts 1 and 2 build the database; parts 3 and 4 read it.

```mermaid
flowchart LR
    A(["Your PDFs"]) --> B["1 · Local extraction"]
    C(["Open sources<br/>on the web"])  --> D["2 · Web scraping"]
    B --> G["3 · Ranking"]
    B --> H["4 · Classification"]
    D --> G
    D --> H
    G --> I(["Ranked materials<br/>+ HTML report"])
    H --> J(["One database<br/>per class"])
```

| # | Part | Reads | Writes |
|---|------|-------|--------|
| 1 | **Local extraction** (`mme-local`) | your PDFs | a database: one CSV per quantity, `database.xlsx`, `database.json` |
| 2 | **Web scraping** (`mme-web`, `mme-dois`) | keywords of a job file | the papers it finds, and a database of the same form as part 1 |
| 3 | **Ranking** (`mme-rank`) | the databases of parts 1 and 2 | the materials ranked by activation energy, and an HTML report |
| 4 | **Classification** (`mme-classify`) | the databases of parts 1 and 2 | one database per crystal-structure type and per structure family |

Each part has its own README with every detail: [LocalExtraction](LocalExtraction/README.md),
[WebScraping](WebScraping/README.md), [SelectingTopMaterial](SelectingTopMaterial/README.md),
[Classification](Classification/README.md).

---

## Installation

### What you need first

| Requirement | Why | How to get it |
|-------------|-----|---------------|
| **Python 3.11 or newer** | runs MME | [python.org](https://www.python.org/downloads/) |
| **Tesseract OCR** | reads scanned or image-only PDFs | macOS: `brew install tesseract` · Ubuntu/Debian: `sudo apt install tesseract-ocr python3-tk` · Windows: [installer](https://github.com/UB-Mannheim/tesseract/wiki) |
| **Google Chrome** | only for web method 2 (moukhlij4scraping) | [google.com/chrome](https://www.google.com/chrome/) |

### Option A — from PyPI

```bash
python3 -m venv .venv                     # create a virtual environment
source .venv/bin/activate                 # enter it (Windows: .venv\Scripts\activate)
pip install moukhlijmatextract            # MME and everything it needs
python -m spacy download en_core_web_sm   # the English language model, once
pip install "moukhlijmatextract[scrape]"  # optional: web method 2 (needs Chrome)
```

### Option B — from the source code

```bash
git clone https://github.com/YounesMoukhlij/MoukhlijMatExtract.git
cd MoukhlijMatExtract
python3 -m venv .venv                     # one virtual environment for the whole project
source .venv/bin/activate                 # enter it (Windows: .venv\Scripts\activate)
pip install -r requirements.txt           # the packages, inside the venv
pip install -e .                          # the mme-* commands, running this folder's code
python -m spacy download en_core_web_sm   # the English language model, once
```

On macOS and Linux, `make install` does all of this in one step.

Work **inside the virtual environment**: in each new terminal, enter it again with
`source .venv/bin/activate` before running MME. Check the installation with:

```bash
mme-gui --version
```

---

## User manual

### Step 0 — Open MME

```bash
mme-gui
```

This opens the main window: one card per part, each with an **Open** button and a
**Delete outputs…** button. The **⚠ Requirements** button at the top opens a short guide to what MME
needs; it turns green (**✓ Requirements**) once you have read it. The bottom of the window describes the
project and its author.

Every part can also be run from the terminal — each step below gives both ways.

#### Where your files go

Every part works inside **`~/MoukhlijMatExtract`** (the folder `MoukhlijMatExtract` in your home
folder), the **main results folder**, whatever folder you start it from. In the main window, press
**Create the main results folder** to make it with every part's folders; once it exists the button reads
**Open the main results folder** and opens it. Opening a part also makes it when it is missing, so the
parts always find each other's files:

```
~/MoukhlijMatExtract/
├── configs/sse.yaml                      ← what the web search looks for (the job file)
├── LocalExtraction/papers/               ← put your own PDFs here
├── LocalExtraction/local_output/         ← database of part 1
├── WebScraping/Fetch_DOIs/               ← DOI list of web method 2 (dois.csv, dois.txt)
├── WebScraping/papers/                   ← PDFs downloaded by part 2
├── WebScraping/web_output/               ← database of part 2
├── SelectingTopMaterial/results/         ← the ranking (part 3)
└── Classification/                       ← the classes (part 4)
    ├── crystal_structure/
    └── structure_families/
```

### Step 1 — Extract your own PDFs

1. Copy your PDFs into `~/MoukhlijMatExtract/LocalExtraction/papers/`.
2. In the main window, open **1 · Local extraction** and press **Start extraction**.
3. Watch the values arrive in the **Activation energies** tab; the **Activity** tab shows the log.

From the terminal:

```bash
mme-local                      # extract the new PDFs of LocalExtraction/papers/
mme-local extract -i ~/Desktop/articles   # another folder of PDFs
mme-local gui                  # the same, in a window
```

| Option | What it does |
|--------|--------------|
| `--input DIR`, `-i` | folder of PDFs (default `LocalExtraction/papers`) |
| `--output DIR`, `-o` | where to write the database (default `LocalExtraction/local_output`) |
| `--workers N`, `-w` | how many PDFs to read at once (default 4) |
| `--offline` | do not complete titles, authors, DOIs and years from OpenAlex |
| `--rebuild` | extract every PDF again (the old database is kept in `previous_<date>/`) |

Only new PDFs are read: a PDF already in the database is reported as `Already extracted … — skipped`.

### Step 2 — Find and extract papers from the web

Open **2 · Web scraping** in the main window. Each time it opens, it asks for your **contact e-mail**
(the open databases ask that callers give one) and points to the API keys. Then choose one of two methods;
both save their PDFs in `WebScraping/papers/` and extract into `WebScraping/web_output/`, so they build
**one** database.

**API keys** are all free and all optional — without any key the open sources still work; each key just
opens more papers. Press **API keys…** in the web window: each card has a link to the sign-up page and a
field for the key.

#### Customize the search — Search settings…

What the web search looks for is kept in `~/MoukhlijMatExtract/configs/sse.yaml`, and both methods use it.
Press **Search settings…** — in the web window, in method 1's window or in method 2's window — to change
it in a form instead of editing the file:

| Tab | What you can change | Used by |
|-----|---------------------|---------|
| **1 · Searches** | the searches, one per line (`# lines` are headings that group them); a file of papers you already know | both methods (the file: method 1) |
| **2 · Sources and years** | the years; how many results each source gives per search (1–1000); which sources are searched; preprints; where missing abstracts are looked up | both methods |
| **3 · Which papers** | the topic, property and excluded words; the minimum score (0–20); whether papers without a free copy are kept | method 1 (topic and property words: both) |
| **4 · Download** | where a legal copy is looked for; downloads at once (1–8); the largest PDF (1–500 MB) | method 1 |
| **5 · Data extracted** | which properties are kept (ion transport, every property, or your choice); whether a value must be tied to a material | both methods |

Each number is held within its bounds, and nothing is saved while a setting is wrong — the form says
what to fix. A source whose key or e-mail is missing is marked so. The comments and headings of the
file are kept. **Reset to defaults** puts back the settings MME comes with (saved only when you press
**Save**). Some settings are not offered because changing them would break MME: the folder of the PDFs
(always `WebScraping/papers/`) and the job's name. The contact e-mail and the keys are set in
**API keys…**. A window whose step is running lets you open the form once the step is done; a step
already running keeps the settings it started with, and the next one uses the new ones.

#### Method 1 — Search the open sources

Searches OpenAlex, arXiv, Crossref, Semantic Scholar, Europe PMC and nine more services by keyword, keeps
the papers on topic, downloads the legal open-access copies and extracts them.

1. Press **1 · Search**. The keywords, years and sources come from the job file
   `~/MoukhlijMatExtract/configs/sse.yaml` — press **Search settings…** to change them.
2. Look through the papers found in the **Candidates** tab.
3. Press **2 · Download** (optionally limit the number of papers; tick *then extract them*).
4. Press **3 · Extract** if you did not let the download extract them.

**Check setup** tests the network, the API keys and the folders.

From the terminal:

```bash
mme-web                        # search, download and extract, as the job file says
mme-web run --check            # test the network, the API keys and the folders
mme-web run --limit 50         # download at most 50 papers in this run
mme-web run --stage extract    # only extract the PDFs already downloaded
mme-web gui                    # the same, in a window
```

| Option | What it does |
|--------|--------------|
| `--job FILE` | another job file (default `configs/sse.yaml`) |
| `--stage discover\|fetch\|extract` | the first stage to run |
| `--yes` | approve every paper found, without a review |
| `--limit N` | download at most N papers in this run |
| `--refresh` | search again the keywords already searched in the last 30 days |
| `--rebuild` | extract every downloaded PDF again |

#### Method 2 — moukhlij4scraping (collect DOIs, then fetch a PDF for each)

Needs Google Chrome and `pip install "moukhlijmatextract[scrape]"`.

1. Press **1 · Fetch DOIs** and say how many **new** DOIs you want. They are added to
   `WebScraping/Fetch_DOIs/dois.csv` and `dois.txt`; a DOI already in the list is never added twice.
   **Fetched DOIs (N)…**, next to it, shows the whole list in a window of its own: the total, which DOIs
   already have their PDF, which were tried without success, which were not tried yet — with title,
   year, journal and every detail of the selected DOI; filter, sort, copy, or open one at doi.org.
2. Press **2 · Scrape articles**, say how many DOIs this run should try (empty: every one left), and
   whether to **start with the legal open-access copies**:
   - **Yes** — step 1 looks for the open-access copy of each DOI (Unpaywall, OpenAlex, arXiv, PubMed
     Central, OSTI, HAL, publisher APIs with your keys …), several DOIs at a time ("Downloads at once" in
     **Search settings…**); step 2 sends the DOIs without an open copy to the other sources, one at a time.
     method 1 (**Search open sources**). A DOI tried this way is tried again the day you answer Yes.
   - A DOI whose PDF is already in `WebScraping/papers/` is skipped; one no source had is skipped for
     30 days. Every DOI tried is written to `WebScraping/papers/scrape_log.csv`. The window shows the step,
     *DOI i of n*, and how many PDFs were saved; the run ends with a summary by source. **Stop** at any time:
     the next run goes on with the rest.
3. Press **3 · Extract** to add them to the web database.

From the terminal:

```bash
mme-dois --count 500                       # add 500 new DOIs to the list
mme-dois "LLZO garnet" "argyrodite"        # your own keywords instead of the job file's
python -m WebScraping.moukhlij4scraping.run --from-fetch -l ~/MoukhlijMatExtract/WebScraping/papers --limit 500
mme-web run --stage extract                # extract the fetched PDFs
```

`--limit N` tries at most N DOIs in this run; `--retry` tries again the DOIs no source had in the last
30 days; `--no-open-access` skips the open-access step (left to method 1).

> Method 2 does not fetch only open-access copies. Check your institution's rules; it is meant for
> academic literature research.

only has a page for a paper someone has requested there; any other DOI is sent to its home page. Method 2
says so for that DOI and goes on with the next source. Before, it went on to load that home page in

### Step 3 — Rank the materials

Open **3 · Ranking** and press **Rank**, or from the terminal:

```bash
mme-rank                       # rank everything, write the files
mme-rank --open                # … and open the report in the browser
mme-rank --element Na          # only the sodium conductors
mme-rank --origin experimental --top 20
mme-rank gui                   # the window
```

**Each transport component is ranked on its own — bulk, grain boundary and total.** A bulk Ea and a
total Ea are different quantities, so they are never mixed: each component has its own ranking, its own
ranks and its own classes. In each, a material gets one activation energy (by default the
confidence-weighted median of its values of that component) and a class from
[`criteria.toml`](SelectingTopMaterial/criteria.toml):

| Class | Activation energy |
|-------|-------------------|
| **Superionic** | below 0.25 eV |
| **Performant** | 0.25 – 0.30 eV |
| **Acceptable** | 0.30 – 0.40 eV |
| **Rejected** | 0.40 eV and above |

| Option | What it does |
|--------|--------------|
| `--policy consensus\|optimistic\|conservative` | which value stands for a material: the median, the lowest or the highest |
| `--origin experimental\|simulation` | only measured, or only computed values |
| `--attribution this-work\|cited` | only the papers' own results, or only the values they cite |
| `--element Li Na …` | only materials containing these elements |
| `--component bulk\|grain_boundary\|total` | rank one component only (by default each is ranked) |
| `--min-confidence 0.5` | only values extracted with at least this confidence |
| `--by-phase` | rank the phases of a composition apart (cubic / tetragonal, …) |
| `--top N` | keep the first N materials |
| `--format csv xlsx json html` | which files to write |
| `--source DIR …` | read other databases (for example one class from step 4) |
| `--force` | rank again even if nothing changed |

Each ranking is written into its own folder — `SelectingTopMaterial/results/bulk/`, `grain_boundary/`
and `total/` — each with `top_materials.csv`, `all_materials.csv`, `values.csv`, `selection.xlsx`,
`selection.json` and `report.html`; `results/summary.csv` puts the components side by side. The window
has a tab per component.

### Step 4 — Classify the materials

Open **4 · Classification** and press **Classify**, or from the terminal:

```bash
mme-classify                   # classify, write one database per class
mme-classify gui               # the window
```

Each material is classified twice:

- by **crystal-structure type** — NASICON, LISICON, thio-LISICON, garnet, argyrodite, LGPS, perovskite,
  antiperovskite, spinel, olivine, … → `Classification/crystal_structure/<class>/`
- by **structure family** — oxide, sulfide, halide, oxyhalide, nitride, hydride, … →
  `Classification/structure_families/<class>/`

`Classification/all_materials.csv` lists every material with its two classes. Each class folder is a
database of the same form as parts 1 and 2, so you can rank one class alone:

```bash
mme-rank --source ~/MoukhlijMatExtract/Classification/crystal_structure/garnet
```

### Seeing every result — Results…

Each part in the main window has a **Results…** button (the extraction windows have it too: **Results →
Browse every table…**, or **Browse every table** on the results card). It opens every table of that part
in one window: the list of tables on the left with their number of rows, the chosen table on the right
with every column — sorted by a click on a heading, searched with one box over all its columns — and
every cell of the selected row below, with a button to open the paper at doi.org.

| Part | Its tables |
|------|-----------|
| 1 · Local extraction | papers, activation energies, ionic and electronic conductivities, diffusion coefficients, all properties, materials, methods, values without a material, the papers' tables, figures, equations, workflow, material ↔ value links, summary per paper |
| 2 · Web scraping | the same for the web database, plus the candidates of method 1, the downloads of method 2 and the DOI list |
| 3 · Ranking | the summary of the components, then for bulk, grain boundary and total: top materials, all materials, values |
| 4 · Classification | every material and its classes, the crystal families and the structure families, each with its Ea by component |

The files are only read: nothing in the window changes them.

### When a step ends — the results card

Every step of every window ends with a **results card** above its tables: ✓ done, ⚠ done with problems
or stopped, ✕ failed, ○ nothing new — with the time it took, big numbers for what it did, the main
findings, and buttons for what comes next.

| Step | The numbers | The findings | Next |
|------|-------------|--------------|------|
| 1 · Local extraction, 2 · Extract (both web methods) | articles read, activation energies, ionic conductivities, materials, PDFs not read | the lowest activation energies and the highest conductivity found, each with its article | show the values, open the workbook or the folder |
| 2 · Search (method 1) | new papers, proposed, no open copy known | the best matches | review them, download them |
| 2 · Download (method 1) | downloaded, failed, no copy to be had | the sources the PDFs came from | extract them |
| 2 · Fetch DOIs (method 2) | new DOIs, DOIs in the list | the new DOIs of each source | show the DOIs, scrape them |
| 2 · Scrape articles (method 2) | PDFs saved, not found, DOIs with their PDF, not tried yet | the sources, the articles saved | extract them, show the DOIs |
| 3 · Ranking | the materials of each component (bulk, grain boundary, total), how many superionic, the best of each | the best two materials of each component, with their article | show each component, open the report, the folder |
| 4 · Classification | materials, crystal families, structure families, activation energies | the largest crystal families, their lowest Ea and its article | show the classes, open the class folders |

**Every table names its articles.** Each CSV of the databases has the article's `title` right after
`paper_id` (the file name stands for a paper that states no title, and says so); the ranking's and the
classification's tables of materials have `articles`, the titles of the papers their values come from;
`scrape_log.csv` has the title of each DOI. A database written before gets the column added the next time
it is opened — nothing is extracted again.

### Running a part again never redoes finished work

Each part says what it skips and moves on to the next item:

| Part | Already done | Message | To redo it |
|------|--------------|---------|------------|
| 1 · Local extraction | a PDF already in the database | `Already extracted: <file> — skipped.` | `--rebuild` |
| 2 · `mme-dois` | a keyword a source answered in the last 30 days | `<source>: already fetched on <date> — skipped` | `--refresh` |
| 2 · `mme-web` | a search run in the last 30 days, a paper already downloaded | `already searched …` / `Already fetched: <doi> …` | `--refresh` / `--rebuild` |
| 2 · moukhlij4scraping | a DOI whose PDF is already in `WebScraping/papers/` | `Already fetched: <doi> — skipped` | delete the PDF |
| 3 · Ranking | the same databases, criteria and options as the last ranking | `Already ranked … — skipped.` | `--force` |
| 4 · Classification | the same databases as the last classification | `Already classified … — skipped.` | `--force` |

### Keeping the results up to date

| After… | Run |
|--------|-----|
| adding PDFs to `LocalExtraction/papers/` | parts 1 → 3 → 4 |
| wanting more papers from the web | parts 2 → 3 → 4 |
| changing the limits in `criteria.toml` | part 3 |
| updating MME | parts 1 and 2 with `--rebuild`, then 3 and 4 |

### Starting a part over — Delete outputs

Press **Delete outputs…** next to a part in the main window, or in the part's own window. It lists what
the part wrote, with the number of files and their size; tick what to delete (for web scraping: the DOI
list, the downloaded PDFs and their ledger, the web database). The files go to the **Trash**, so they can
be got back. Your own PDFs, the job file and the API keys are never offered, and a part that is running
cannot be emptied until it is done.

### All commands

| Command | Does |
|---------|------|
| `mme-gui` | the main window: every part, one button each |
| `mme-local` | 1 · extract your PDFs (`mme-local gui`: in a window) |
| `mme-web` | 2 · method 1: search, download and extract (`mme-web gui`: in a window) |
| `mme-dois` | 2 · method 2: collect DOIs |
| `mme-rank` | 3 · rank by activation energy (`mme-rank gui`: in a window) |
| `mme-classify` | 4 · classify by structure (`mme-classify gui`: in a window) |

Add `--help` to any command for all its options.

### Troubleshooting

| Problem | Fix |
|---------|-----|
| `no database to classify` / `no results folder` | run part 1 or 2 first, or name a database with `--source DIR` |
| scanned PDFs give no values | install Tesseract (see *What you need first*) |
| `Can't find model 'en_core_web_sm'` | `python -m spacy download en_core_web_sm` inside the venv |
| `mme-…: command not found` | enter the venv: `source .venv/bin/activate` |
| the web search finds few papers | add free API keys (**API keys…**), or run `mme-web run --check` |
| method 2 fails to start | install Google Chrome and `pip install "moukhlijmatextract[scrape]"` |
| method 2 finds few PDFs | the open-access step finds the legal copies; set your contact e-mail and keys in **API keys…** (Unpaywall needs the e-mail) |

---

## For developers

```bash
make test        # every test of the four parts (python -m pytest)
make help        # every make target
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [CHANGELOG](CHANGELOG.md).

## About the author

**Younes Moukhlij** is a PhD researcher working on solid-state electrolytes at the Faculté
Polydisciplinaire de Khouribga (FPK), Université Sultan Moulay Slimane (USMS), and a software-engineering
student at 1337 Coding School. MME brings the two together: software engineering put to work for
materials research.

Contact: [younes.moukhlij@usms.ac.ma](mailto:younes.moukhlij@usms.ac.ma)

## Cite

If you use MME in your research, please cite it — see [`CITATION.cff`](CITATION.cff). GitHub shows a
**Cite this repository** button on the repository page.

## License

[MIT](LICENSE) © 2026 Younes Moukhlij
