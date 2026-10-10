# AutoMatExtract

**Author:** Younes Moukhlij — Software Engineering student at 1337 Coding School,
PhD researcher at USMS.

AutoMatExtract turns a folder of battery/materials-science PDFs into a structured, queryable
database. It parses each paper (text, tables, figures, equations, OCR fallback for scanned
pages), pulls out materials and their properties with SpaCy/regex/PyMatgen, ranks and
deduplicates candidate values, links materials to properties, and exports everything as linked
CSV files, a multi-sheet Excel workbook, and nested JSON.

AutoMatExtract has **three parts**, used one after the other:

| Part | What it does | Command | Result |
|---|---|---|---|
| **1 · Local** | Extracts materials and their activation energies from the PDFs you put in `papers/` | `python main.py local` | `local_output/` |
| **2 · Web** | Searches the literature online, lets you review what it found, fetches the legal copies into `papers/web/` and extracts from them | `python main.py web --job configs/sse.yaml` | `web_output/` |
| **3 · Rank** | Reads the activation energies of both databases and sorts the materials into Superionic, Performant, Acceptable or Rejected | `python -m SelectingTopMaterial` | `SelectingTopMaterial/results/` |

Parts 1 and 2 are two **projects** — the articles on your computer, the articles from the web — and
**two gates** lead to them: the terminal and a window. Both gates run the same code and write the
same files, so results never differ between the two and a run started in one can go on in the
other. The results of the two projects are kept apart: `local_output/` and `web_output/`. Part 3
only reads them. New here? Start with [Using the whole project, step by step](#using-the-whole-project-step-by-step).

| Gate | Command | What it does |
|---|---|---|
| Terminal | `python main.py local` | Project 1: extracts from the PDFs you put in `papers/` into `local_output/` (plain `python main.py` still means this) |
| Terminal | `python main.py web --job configs/sse.yaml` | Project 2: searches the literature online, lets you review what it found, fetches the legal copies into `papers/web/` and extracts from them into `web_output/` — see [Project 2](#project-2-the-web-project) |
| Terminal | `python main.py both --job configs/sse.yaml` | The web project (up to your review), then your own PDFs, each into its own folder |
| Window | `python main.py gui` | Both projects side by side, each with its folder of results — see [The window](#the-window) |

## Using the whole project, step by step

Each part is its own command and reads what the one before it wrote. You may run part 1, part 2 or
both, then part 3 on whatever exists. All commands are run from the project folder (`python3` instead
of `python` where `python` is not found).

### 0 · Install once

Follow [Installation](#installation). Parts 1 and 2 need Python 3.9+, Tesseract and the packages of
`requirements.txt`. Part 3 needs nothing more, but **Python 3.11+** (it reads its criteria with the
standard `tomllib`); only its Excel file needs `openpyxl`, which `requirements.txt` already has.

### 1 · Local — extract from your own PDFs

```bash
# put the PDFs at the top level of papers/, then:
python main.py local
```

Open `local_output/activation_energy.csv` (or `database.xlsx`) to see what was found. Running it
again only reads PDFs that are new; `--rebuild` reads all of them again. Details:
[Command line (Project 1)](#command-line-project-1).

### 2 · Web — find and fetch papers

```bash
cp .env.example .env                                         # optional: your e-mail and keys (Elsevier, Wiley)
python main.py web --job configs/sse.yaml --check            # test the setup
python main.py web --job configs/sse.yaml                    # search + screen, then it stops
#   open papers/web/candidates.csv, set `decision` to yes or no for each paper, save
python main.py web --job configs/sse.yaml --stage fetch      # fetch what you approved, then extract it
```

What to search for is in `configs/sse.yaml` (queries, years, screening words). The PDFs land in
`papers/web/` and the database in `web_output/`. To try it small, add `--limit 10` to the last
command. Details: [Project 2](#project-2-the-web-project).

Both parts at once: `python main.py both --job configs/sse.yaml` runs the web project up to your
review, then your own PDFs. Or use the window: `python main.py gui` (see [The window](#the-window)).

### 3 · Rank — find the best materials

```bash
python -m SelectingTopMaterial            # both databases together
python -m SelectingTopMaterial --open     # ...and open the report in the browser
```

The terminal shows how many materials each class holds and the ones that pass, best first; the
same ranking is written to `SelectingTopMaterial/results/` (`top_materials.csv`, `report.html`,
`selection.xlsx`, ...). Details: [Project 3](#project-3-ranking-the-best-materials).

### Keeping it up to date

| You did | Run again |
|---|---|
| Added PDFs to `papers/` | `python main.py local`, then part 3 |
| Want more web papers | `python main.py web --job configs/sse.yaml`, review, `--stage fetch`, then part 3 |
| Updated the program, tables look old | `python main.py local --rebuild` (and `--stage extract --rebuild` for the web), then part 3 |
| Changed the classes or limits | Only part 3: edit `SelectingTopMaterial/criteria.toml` and run it again |

Part 3 rewrites `SelectingTopMaterial/results/` each time; give another `--out` folder to keep a
ranking you want to compare with.

## Features

- **PDF parsing** — text, tables, and captions via PyMuPDF/pdfplumber, with per-block page and
  section tracking so every extracted value keeps its provenance.
- **OCR fallback** — scanned/image-only pages are rendered at 400 DPI, cleaned up with OpenCV
  (denoise, sharpen, adaptive threshold), and read with Tesseract.
- **NLP + rule-based extraction** — SpaCy dependency parsing and regex patterns pull materials,
  properties (electrochemical, thermodynamic, mechanical, structural, electronic, thermal,
  spectroscopy), and computational parameters (DFT, AIMD, ML) out of running text and tables.
- **Transport values read value-first** — every number carrying the unit of a conductivity, a
  diffusion coefficient or an activation energy is a candidate, so "… and 0.45 eV for the tetragonal
  phase", "LLZO (0.31 eV), LATP (0.35 eV)" and "Li10SnP2S12 (3.8 × 10⁻³ S cm⁻¹)" are found too, not
  only what follows a keyword.
- **One activation energy** — activation energy, Ea, migration / hopping / diffusion / energy
  barrier: one property, one numeric column in eV, with the paper's own word kept beside it.
- **Chemistry-aware materials** — formulas are read with the real element symbols, including
  fractional and variable subscripts (`Li2Sc2/3Cl4`, `Li3−xY1−xZrxCl6`), mixtures
  (`0.8Li2O–ZrCl4`, `70Li2S-30P2S5`) and the paper's own abbreviations; acronyms, polyanions and
  citation numbers run into a formula are told apart from materials (PyMatgen data, Pint units).
- **Ranking & deduplication** — multiple candidate values for the same property are scored and
  reduced to the best-supported ones, with a confidence score and full source trace.
- **Where each value comes from, and what it is for** — every value says whether it was read in
  the running text, a figure caption or a table (and on which page), which material it belongs to
  (formula, composition, structure, ionic radii), at what temperature and pressure it holds,
  whether it is experimental or simulated, whether it describes bulk, grain-boundary, surface or
  total transport, and whether it is the paper's own result or one it cites. What the value's
  sentence leaves out is looked for in the sentences before it, the caption it points to and the
  paper's methods — and `basis` records where each answer was found. See
  [Value context](#value-context).
- **A complete row for every activation energy** — no cell of `activation_energy.csv` is empty:
  what the paper leaves unsaid is answered with the likeliest value, marked `assumed` with its
  reason and counted in `n_assumed`, so that a default is never taken for a statement of the paper.
- **Incremental runs** — re-running the pipeline on the same output folder skips papers that are
  already in `papers.csv` and only processes new PDFs; `--rebuild` extracts everything again.
- **Multiple export formats** — normalized relational CSVs (`papers`, `materials`, `properties`,
  `activation_energy`, `unassigned_values`, `methods`, `relations`, `tables`, `figures`,
  `equations`, `workflow`), a multi-sheet Excel workbook, nested JSON, and a flat one-row-per-paper
  summary CSV for quick scanning.
- **Two gates** — a scriptable command-line interface, and a window with the local articles on
  one side and the web articles on the other: review the candidates in a table, watch each
  download and each extraction, see the activation energies as they land in the database.
- **A web project that fills the folder for you** — search OpenAlex and arXiv, screen the hits by
  title and abstract, review them, then fetch open-access PDFs (and Elsevier ones through
  Elsevier's own API) with their provenance recorded. See [Project 2](#project-2-the-web-project).
- **A ranking of the best materials** — the activation energies of both databases are brought
  together, one value per material is chosen, and each material is sorted into Superionic,
  Performant, Acceptable or Rejected, with the paper, page and sentence behind every value and a
  flag where the values disagree. See [Project 3](#project-3-ranking-the-best-materials).

## How it works

```
papers/*.pdf
    │
    ▼
parser.py        — PyMuPDF/pdfplumber: text blocks, tables, sections, references
    │ (falls back to ocr.py for image-only pages)
    ▼
extractor.py     — SpaCy NLP + regex + PyMatgen: candidate materials & properties
    │
    ▼
ranking.py       — dedupe candidates, score confidence, keep the best value per property
    │
    ▼
pipeline.py      — orchestrates parsing/extraction/ranking across PDFs (ThreadPoolExecutor)
    │
    ▼
exporter.py      — writes local_output/ or web_output/ {database.json, database.xlsx, *.csv}
```

Project 2 is a front end for the same pipeline — it only replaces getting the PDF by hand:

```
python main.py web --job configs/sse.yaml
    │
    ▼
web/sources      — OpenAlex + arXiv: candidates (title, abstract, DOI, where a legal copy is)
    ▼
web/screening    — score from title/abstract, flag preprints/duplicates/retractions → candidates.csv
    ▼
 you review      — set the `decision` column to yes/no
    ▼
web/resolve+fetch— publishers' APIs → open links → arXiv → repositories (PubMed Central, OSTI, HAL, ...);
                   only a real PDF with the right title is kept
    ▼
papers/web/*.pdf (+ .json provenance, ledger.sqlite) ──▶ the pipeline above, unchanged
```

`models.py` defines the shared dataclasses (`PaperData`, `Material`, `ExtractedField`,
`Relation`, ...) that flow through every stage, and `normalizer.py` / `config.py` hold the
scientific value/unit normalization and regex/context configuration used by the extractor.
`chemistry.py` finds the materials (and derives their ionic radii and structure family) and
`quantities.py` the transport values of a sentence. `transport.py` and `context.py` work out what
each value describes from its own sentence — its transport component, and the temperature,
pressure, data origin and crystal structure stated with it — and `study.py` reads what the paper
states once for all its values (what kind of study it is, the temperature range of its
measurements or simulations), for the values whose sentence is silent.

Part 3 starts where the two above end. It only reads the `activation_energy.csv` and `papers.csv`
of the results folders and imports none of the code of parts 1 and 2:

```
local_output/ + web_output/  (output/ of earlier versions, when present)
    │
    ▼
loader.py        — reads activation_energy.csv + papers.csv; a paper held by two folders counts once
    ▼
selection.py     — one group per material (its composition), one Ea per group (the policy)
    ▼
criteria.py      — Ea < 0.25 Superionic · < 0.30 Performant · < 0.40 Acceptable · otherwise Rejected
    ▼
exporters.py / html_report.py / console.py — CSV, Excel, JSON, report.html, the terminal
```

## Platform support

Linux, macOS, and Windows are all supported — the codebase uses only `os.path`, UTF-8 I/O, and
cross-platform libraries throughout (no OS-specific paths or shell calls). A few
platform-specific setup steps:

- **Tesseract OCR** is installed differently per OS (see Installation below). On Windows, the
  installer doesn't reliably add `tesseract.exe` to `PATH`; `ocr.py` auto-detects the default
  install location (`C:\Program Files\Tesseract-OCR\tesseract.exe`), or you can set the
  `TESSERACT_CMD` environment variable to its full path if installed elsewhere.
- **The window (`gui/`)** uses Tkinter, which ships with the standard Python installer on Windows
  and macOS. On Linux, it's often a separate OS package — e.g. `sudo apt install python3-tk`.

## Installation

Requires **Python 3.9+** and a system install of **Tesseract OCR** (used for scanned pages).
The ranking (part 3) needs **Python 3.11+**.

```bash
# Tesseract (system dependency)
brew install tesseract              # macOS
sudo apt install tesseract-ocr      # Debian/Ubuntu
sudo apt install python3-tk         # Debian/Ubuntu, only for the window (python main.py gui)
# Windows: download the installer from https://github.com/UB-Mannheim/tesseract/wiki

# Python dependencies
pip install -r requirements.txt

# SpaCy language model (not pinned in requirements.txt)
python -m spacy download en_core_web_sm
```

The web project also needs `requests` and `pyyaml` (both in `requirements.txt`). Its optional keys
and your contact email go in a `.env` file — see [Project 2](#project-2-the-web-project).

## Usage

### Command line (Project 1)

```bash
# Process every PDF in ./papers, write results to ./local_output
python main.py            # the same as: python main.py local

# Custom input/output directories and worker count
python main.py local --input papers --output local_output --workers 4

# Verbose (debug) logging
python main.py -v
```

| Flag | Short | Default | Description |
|---|---|---|---|
| `--input` | `-i` | `papers` | Directory containing input PDFs |
| `--output` | `-o` | `local_output` (`web`: `web_output`) | Directory to write the extracted database into. `both` writes two and has `--local-output` and `--web-output` instead |
| `--workers` | `-w` | `4` | Number of PDFs to process in parallel |
| `--verbose` | `-v` | off | Enable debug-level logging |
| `--rebuild` | | off | Extract every PDF again instead of only the new ones; the present database files are moved to `<output>/previous_<date>/`, not deleted |
| `--gui` | | off | Open the window instead (the same as `python main.py gui`) |

Re-running the command on the same `--output` directory is safe and incremental: papers already
recorded in its `papers.csv` are skipped, and only new PDFs are processed and merged in. Papers
are saved to the database every 50 papers rather than only at the end, so a crash or a Ctrl-C in
a long run loses at most one batch; the Excel workbook is built once, at the end, from the CSVs.
(Only the top level of `papers/` is read: PDFs fetched by the web project live in `papers/web/`.)

### The window

```bash
python main.py gui                       # or: python main.py --gui, or: python -m gui
python main.py gui --input papers --local-output local_output --web-output web_output --job configs/sse.yaml
```

One window, two panels side by side, each with its own folder of results:

```
┌ AutoMatExtract ───────────────────────────────────────── PDFs read at once: [4] [Settings…] ┐
├──────────────────────────────────┬──────────────────────────────────────────────────────────┤
│ Local articles                   │ Web articles                                             │
│ Folder of PDFs: [papers]         │ Job file:       [configs/sse.yaml] [Edit…] [Check setup] │
│ Results folder: [local_output]   │ Results folder: [web_output]                             │
│ [Start extraction] [Stop]        │ [1 · Search] [2 · Download] [3 · Extract] [Stop]         │
│                                  │                                                          │
│ ┌ Activation energies ┬ Activity │ ┌ Candidates ┬ Activation energies ┬ Activity            │
│ │ material  Ea  from  page  ...  │ │ ✓  score  access  state  year  title  ...              │
└──────────────────────────────────┴──────────────────────────────────────────────────────────┘
```

- **Local articles** (left) is `python main.py local`: it reads the PDFs of a folder that its
  results folder (`local_output`) does not hold yet, shows each paper as it is done, and then its
  activation energies.
- **Web articles** (right) is `python main.py web`, one button per stage. *Search* asks the
  sources and screens the hits. The **Candidates** table is the review: filter it, select rows and
  press ✓ Yes / ✗ No — or the keys y and n — (a double click shows the abstract and why the paper
  was proposed). It is the
  same list as `papers/web/candidates.csv` — a list reviewed in a spreadsheet shows up here, and
  what you decide here is what the terminal's fetch stage reads. *Download* fetches the papers
  marked yes, each line saying where the copy came from or why none was had; *Extract* reads the
  downloaded articles into its results folder, `web_output` (by default right after the download).
- **Two folders of results.** Each side writes its own, so the two can work at the same time and
  what was read from your own PDFs is never mixed with what was fetched. Each table shows the
  activation energies of its folder — the material, the value, the part of the paper it was read
  from (text, table or figure) and the page, how many of its answers are defaults — and a double
  click shows the sentence, the `basis` and every other column. The *Results* menu opens the
  folder or the Excel workbook.
- **Settings…** holds the contact address and the keys of the web side (Elsevier, Wiley, ...).
  They are saved in the `.env` file next to `main.py`, which git ignores.
- **Edit…** shows the job as a form — queries, years, screening words, sources, the properties to
  keep — and saves it as a job file the terminal reads too. **Check setup** is `--check`.
- **Results → Rebuild…** moves the database of that side into a `previous_<date>` folder so that
  its articles are extracted again (after an update of the program); nothing is deleted. A
  database written by an earlier version is offered the same when an extraction starts.

Stop lets the papers in progress finish, so their work is not lost; everything is resumable.

## Project 2: the web project

Instead of collecting PDFs by hand, describe what you are looking for and let the program find the
papers, fetch the ones you can legally read, and extract from them with the same pipeline.

```bash
python main.py web --job configs/sse.yaml --check        # 1. test the setup first
python main.py web --job configs/sse.yaml                # 2. search + screen, then stop for your review
#    open papers/web/candidates.csv, set `decision` to yes/no, save
python main.py web --job configs/sse.yaml --stage fetch  # 3. fetch what you approved, then extract it
```

The same steps are buttons in [the window](#the-window) (`python main.py gui`), with the review
done in a table instead of a spreadsheet.

A run is resumable at every step (everything is recorded in `papers/web/ledger.sqlite`): run the
same command again after a crash, a Ctrl-C or a review and it carries on, never fetching a paper
twice. `--limit N` fetches at most N papers in one run (a good way to try it); `--yes` approves
every proposal without a review; `--stage extract` only extracts what is already fetched.

### The stages

1. **Discover** — every query in the job is asked of OpenAlex (journals, arXiv and ChemRxiv alike;
   it also says whether and where a legal open-access copy exists, and flags retractions) and of
   arXiv. A list of DOIs / links / arXiv ids you already know can be added (`search.ids_file`).
2. **Screen** — each candidate gets a score from its title and abstract (a topic word and a
   property word must both appear; a word in the title counts 2, in the abstract 1; each exclude
   word costs 3), and flags: `preprint`, `review`, `RETRACTED`, `no-abstract`, `no-open-copy-known`,
   `duplicate-of:<paper>` (a preprint and its journal version are one paper; the published, fetchable
   one wins). The result is `papers/web/candidates.csv` — open it in a spreadsheet, sorted best
   first, with a `why` column showing which words scored. The `access` column says how a copy is
   expected to be had: `open`, through a publisher's API (`elsevier`, `wiley`), or `closed` — no
   open copy is known to the search. A closed paper is not proposed, unless the job sets
   `screen.propose_closed`: then the fetch stage asks the repositories for the authors' manuscript.
3. **Review** — set `decision` to `yes` or `no` (empty = still waiting) and save. The file may be
   saved by Excel with `;` between columns or in Windows-1252: both are read.
4. **Fetch** — for each approved paper the sources are tried in the job's order (`fetch.sources`,
   see [Where a copy is looked for](#where-a-copy-is-looked-for)): the publisher's own API, the
   open links OpenAlex knows (a landing page is followed to the PDF it declares for search
   engines), Unpaywall, arXiv, then the repositories. A file is kept only if it is a real PDF (not the
   paywall page a server sometimes sends under a `.pdf` name), at least article-sized, and its
   first pages carry the paper's title (not a supplement or another article). A refusal (401/403)
   or a `robots.txt` "Disallow" just means "next source" — nothing tries to get around one.
   Failures are retried on the next runs, three attempts in all; a paper with no legal copy is
   marked `closed` ("needs a manual PDF": drop it into `papers/` and Project 1 handles it).
5. **Extract** — Project 1's pipeline over `papers/web/`, with the metadata the source reported
   (a better title, journal and DOI than can be guessed from a PDF's first page), and only the
   data you asked for (`extract.properties`, `extract.require_material`). The result goes to
   `web_output/` (`--output` to choose another folder), apart from that of your own PDFs.

### What lands where

| Path | What |
|---|---|
| `papers/web/<doi>.pdf` | A fetched paper, named from its DOI (`arxiv_<id>.pdf` for an arXiv-only paper), so its `paper_id` is stable across runs |
| `papers/web/<doi>.json` | Its provenance: DOI, title, source, URL, license, retrieval date, SHA-256, page count, how well the title matched |
| `papers/web/ledger.sqlite` | One row per paper ever found, with its status: new → screened → approved/rejected → downloaded/closed/failed → extracted |
| `papers/web/candidates.csv` | The review list |
| `web_output/papers.csv` | The database of the web papers: `origin` = `web`, and `source_service`, `source_url`, `license`, `retrieved_at`, `file_sha256`, `openalex_id` (in `local_output/`, `origin` = `local` and the rest is `NONE`) |

`papers/web/` and `.env` are git-ignored: the PDFs are someone else's copyright and the keys are secret.

### The job file

`configs/sse.yaml` is a ready-made example for solid-state electrolytes. Every key is optional
except `search`; a key the loader does not know is an error (a misspelled `min_score` would
otherwise quietly keep its default).

| Key | Meaning |
|---|---|
| `contact_email` | Sent to OpenAlex and Unpaywall as the contact for polite use of their free APIs (Unpaywall requires one). Or set `AUTOMATEXTRACT_EMAIL`. It is never sent anywhere else |
| `search.queries` / `ids_file` / `years` / `sources` | What to search for, papers you already know, `[first, last]` year, and `openalex` / `arxiv` |
| `search.max_per_query`, `include_preprints` | How many candidates each source returns for each query (default 200) and whether preprints count |
| `screen.topic_words`, `property_words`, `exclude_words`, `min_score` | The screening rule above |
| `screen.review` | `true` (default): stop after screening so you can review. `false`: fetch the proposals straight away |
| `screen.propose_closed` | `false` (default): a paper no open copy is known for is not proposed. `true`: it is, and the fetch stage asks every source for a copy; the ones nobody has end as `closed` — your list of papers to get by hand |
| `fetch.folder`, `sources`, `workers`, `max_pdf_mb` | Where PDFs go (`papers/web`), the sources and the order they are tried in (default: all of the table below), parallel downloads (3), size cap (60 MB) |
| `extract.properties` | The wished data: only these properties are exported (empty = every property); names as in `properties.csv`, e.g. `Activation_Energy` — which covers migration barriers and every other name of it (a job file that still lists `Migration_Barrier` keeps working) |
| `extract.require_material` | Drop a numeric value that cannot be tied to a material (otherwise it goes to `unassigned_values.csv`) |

### Where a copy is looked for

Every source is a place that may lawfully give the paper to a program: the publisher's own
interface for it, an open-access link, or a repository the authors or their funder deposited the
paper in. They are tried in this order; a later one is only asked when the ones before it gave
nothing that could be kept.

| `fetch.sources` | What it is | Needs |
|---|---|---|
| `elsevier` | Elsevier's API: its open-access articles, and those your institution subscribes to | `ELSEVIER_API_KEY` (free) |
| `wiley` | Wiley's text-and-data-mining API: its open-access articles, and subscribed ones from your university's network | `WILEY_TDM_TOKEN` (free) |
| `aps` | The American Physical Society's API for its open-access articles (Physical Review ...) | — |
| `openalex` | The open-access links OpenAlex found with the paper: publisher, repository | — |
| `unpaywall` | The open-access links Unpaywall knows, often more repository copies | a contact email |
| `arxiv` | The paper's arXiv version | — |
| `pmc` | PubMed Central's open-access set, read from the copy NCBI keeps in the cloud for programs | — |
| `osti` | OSTI.GOV: the accepted manuscript of work funded by the US Department of Energy | — |
| `hal` | HAL, the French open archive: the file deposited by the authors | — |
| `semanticscholar` | The arXiv version Semantic Scholar matched to a journal paper, and the repository copy it knows | — (`SEMANTIC_SCHOLAR_API_KEY` makes it steadier) |
| `openaire` | The copies in the university and national repositories OpenAIRE harvests | — |

The last five look a paper up by its DOI, which is how a paper the search calls closed can still
arrive: its authors' manuscript sits in a repository (`screen.propose_closed`). What a repository
holds is usually that accepted manuscript — the same text and numbers as the journal's version,
not its layout. `source_service` in `papers.csv` says where each file came from.

`python main.py web --job configs/sse.yaml --check` shows which of these can be reached from where
you are and whether your keys work.

What to expect, from a sample of the solid-electrolyte job (October 2026): of 40 open-access
papers, OpenAlex's links and arXiv alone delivered 16, and the repositories brought that to 23
(PubMed Central 4, OpenAIRE 2, HAL 1). Of the 17 that still failed, 10 were open-access papers of
Wiley and Elsevier, whose web pages refuse scripts — that is what their two free keys are for —
and the others sat behind a bot check (MDPI, RSC, ChemRxiv, one repository). Of 40 papers the
search called closed, 1 had a deposited manuscript (OSTI): `screen.propose_closed` is worth
switching on for the list of papers to get by hand more than for the downloads.

### Elsevier / ScienceDirect

Elsevier papers are fetched through Elsevier's own API — the sanctioned way to read, by machine,
what a subscription includes — not by scraping ScienceDirect pages. You need:

1. an **API key** (free): https://dev.elsevier.com/ → "I want an API key", created while you are
   on your university's network;
2. the key in a `.env` file next to `main.py` (copy `.env.example`): `ELSEVIER_API_KEY=...`;
3. to run from the **university network or VPN** — the API only returns full texts for the
   institution the key belongs to — or to ask Elsevier for an **institutional token**
   (`ELSEVIER_INSTTOKEN=...`), which lets the key work from anywhere.

Run `python main.py web --job configs/sse.yaml --check` to see exactly what your key can do
(key accepted? full text as XML? as PDF?). Elsevier limits use to non-commercial text mining and to
a weekly quota; when the quota or the key is refused the Elsevier source is switched off for the
rest of the run. Without a key, Elsevier papers can only come from open-access copies.

### Wiley

Wiley's web pages turn scripts away, also for open-access articles; its text-and-data-mining API
is the way it offers instead. Sign in at
https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining, accept the agreement,
and put the token in `.env`: `WILEY_TDM_TOKEN=...`. It fetches Wiley's open-access articles from
anywhere and the subscribed ones from your university's network, at no more than 60 requests in
10 minutes (the program waits accordingly). `--check` tells you whether the token works.

### Good citizenship

Every service is used through the interface it offers to programs, with your contact address in
the User-Agent when you give one. Requests are spaced per host (arXiv: 3 s for its API; 15 s
between PDF downloads, as its `robots.txt` asks of generic crawlers — `Crawl-delay` is obeyed for
every site), retried with back-off, and `robots.txt` is honoured for every file or page; a service
that keeps answering "too many requests" is left alone for the rest of the run. Nothing here
bypasses a paywall, a login, a bot check or a refusal, and shadow libraries (Sci-Hub and the like)
are not used and cannot be added as a source: they hand out papers without the right to. Papers
with no legal copy stay a manual step — your library, an inter-library loan, or a request to the
authors.

### Tests

```bash
python -m unittest discover -s tests -v     # or: pytest tests
```

The tests of the web project run offline: every network call is answered by a fake session.
`tests/test_extraction.py` checks, on sentences, which numbers are read as which quantity, which
material each is tied to and where its context comes from. `tests/test_gui.py` builds the window
(transparent, on a made-up database) and drives both panels; without a screen those tests are
skipped.

## Project 3: ranking the best materials

`SelectingTopMaterial/` reads the activation energies that parts 1 and 2 extracted and ranks the
materials by them:

| Activation energy | Class |
|---|---|
| Ea < 0.25 eV | **Superionic** |
| 0.25 ≤ Ea < 0.30 eV | **Performant** |
| 0.30 ≤ Ea < 0.40 eV | **Acceptable** |
| Ea ≥ 0.40 eV | Rejected |

Every limit is exclusive: a material at exactly 0.25 eV is Performant, one at exactly 0.40 eV is
Rejected. It only **reads** the results folders (`local_output/`, `web_output/` and the `output/` of
earlier versions, whichever exist) and writes into its own `SelectingTopMaterial/results/`; it
changes nothing of the rest of the project.

```bash
python -m SelectingTopMaterial                          # both databases, everything written
python -m SelectingTopMaterial --source web_output      # one database only
python -m SelectingTopMaterial --top 10 --open          # the first ten, and the report in the browser
python -m SelectingTopMaterial --no-files               # show the ranking, write nothing
```

An excerpt of what it says (on the databases of October 2026: 33 values from 13 papers, 19 materials):

```
  ◆ Superionic   Ea < 0.25 eV          7 materials
  ● Performant   0.25 ≤ Ea < 0.30 eV   3 materials
  ○ Acceptable   0.30 ≤ Ea < 0.40 eV   5 materials
  × Rejected     Ea ≥ 0.40 eV          4 materials

   #  Material       Class         Ea (eV)  Range (eV)     Values  Papers  Origin         Checks
   1  Li3PS4         ◆ Superionic    0.120  0.080 – 0.160       2       1  simulation     ok
   2  Li10GeP2S12    ◆ Superionic    0.150  0.150 – 0.226       2       2  simulation     low confidence
   5  NaLaCl4        ◆ Superionic    0.210  0.040 – 0.650       3       1  exp 1 · sim 2  values disagree (Superionic to Rejected)
```

### What it writes

| File (in `SelectingTopMaterial/results/`) | Contents |
|---|---|
| `top_materials.csv` | The materials that pass (Superionic, Performant, Acceptable), lowest Ea first |
| `all_materials.csv` | Every material with its class, the rejected ones too |
| `values.csv` | Every activation energy behind them, with its own class, paper, DOI, page and sentence |
| `selection.xlsx` | The three tables and the rule, in one workbook |
| `selection.json` | Everything as nested JSON, each material with its values |
| `report.html` | One self-contained page: a chart of every material against the limits, and a table where each material opens onto the values it stands on |

Like `activation_energy.csv`, no cell is empty: what the database does not say is `not reported`.
The columns are described in [SelectingTopMaterial/README.md](SelectingTopMaterial/README.md).

### How a material gets its class

- **One material is one composition.** The values are grouped by composition, so
  `Li1.3Al0.3Ti1.7(PO4)3` and `Li1.3Ti1.7Al0.3(PO4)3` are one material, in whatever paper. With
  `--by-phase` the phases the database names are ranked apart (`Li7La3Zr2O12 (cubic)` and
  `(tetragonal)`, `Li3PS4 (β-phase)` and `(γ-phase)`).
- **One material, one Ea.** A material often has several values. Which one stands for it is the
  *policy*: `consensus` (the default; the confidence-weighted median, so one outlier does not
  decide), `optimistic` (its lowest value) or `conservative` (its highest).
- **Each paper counts once.** A paper that two folders hold (`output/` is often an earlier copy of
  `local_output/`; an article can be in `papers/` and fetched from the web too) is read from the
  first folder only. Papers are matched by DOI when `papers.csv` has it, by file name otherwise.
- **What is unsure is written, not hidden.** The `checks` column says `ok`, or:
  `borderline (0.25 eV limit)` (within 0.01 eV of a limit), `values disagree (Superionic to
  Rejected)` (the material's values fall on both sides of a limit; `class_of_values` counts them),
  or `low confidence` (mean extraction confidence below 0.5). A check never moves a material.
- **What cannot be ranked is counted.** Activation energies the extraction tied to no material are
  in `unassigned_values.csv`; the ranking says how many there are.

### Options

| Flag | Effect |
|---|---|
| `--source DIR ...` | Results folder(s) to read, the most trusted first (default: every one that exists) |
| `--out DIR` | Where to write (default: `SelectingTopMaterial/results`) |
| `--origin experimental` / `simulation` | Only measured values, or only computed ones |
| `--attribution this-work` / `cited` | Only the papers' own results, or only what they cite |
| `--component NAME` | One transport component: `bulk`, `total`, ... |
| `--element Na` | Only materials containing these elements |
| `--min-confidence 0.5` | Leave out the least sure extractions |
| `--policy` | `consensus`, `optimistic` or `conservative` |
| `--by-phase` | Rank the phases of a composition apart |
| `--top N`, `--format csv xlsx json html`, `--open`, `--no-files`, `--quiet`, `--no-color` | What is shown and written |
| `--criteria FILE` | Use another criteria file |

`--help` lists them all. The command ends with 0 when a ranking was written, 1 when there was
nothing to rank or a file could not be written, 2 when it was asked something it cannot do.

### Changing the rule

The classes are in `SelectingTopMaterial/criteria.toml`, not in the code: their names and limits,
the default policy, and what counts as borderline or low confidence. Edit it, or write another and
pass it with `--criteria`. Classes are listed best first with rising limits; a file that breaks
that is refused with the reason. Decimals are written with a point (`0.25`).

### From Python

```python
from SelectingTopMaterial import PROJECT_ROOT, Criteria, Filters, discover, select_from

ranking = select_from(discover(PROJECT_ROOT), Criteria.load(), filters=Filters(origin="experimental"))
for material in ranking.top:
    print(material.rank, material.material, material.energy_class.name, material.energy_eV)
```

### Tests

```bash
python -m unittest discover -s SelectingTopMaterial/tests -t .     # or: pytest SelectingTopMaterial
```

They run on small made-up databases in a temporary folder and never read or write the project's
own results.

## Output

Each project fills its own folder — `local_output/` for the articles of your computer,
`web_output/` for the articles fetched from the web — with the same files:

| File | Contents |
|---|---|
| `papers.csv` | One row per paper: title, authors, journal, DOI, year, counts, and where it came from (`origin`, plus for web papers the source, URL, license, retrieval date and checksum) |
| `materials.csv` | Every material found: its formula as the paper wrote it (`raw_formula`) and in one spelling per composition (`normalized_formula`), `elements` (the composition), `structure` with its `structure_basis`, and `ionic_radii` |
| `properties.csv` | **The values of materials**: one row per number that was tied to a material, with its unit, confidence and full [value context](#value-context). Every value of a material is kept (up to 25 per property and transport type, a guard against a table read wrongly) |
| `activation_energy.csv` | The activation energies among them, in one numeric column — whatever the paper called it: see [One activation energy](#one-activation-energy) |
| `unassigned_values.csv` | The values no material could be established for (a class of materials, a sample label the paper never defines, a sentence cut by a page break). Same columns as `properties.csv`, without the material ones |
| `methods.csv` | How the study was done and what it mentions: DFT / AIMD / ML settings, synthesis conditions, characterization techniques, structure mentions. These have no material and no measurement context, so they have no such columns |
| `relations.csv` | Every material ↔ property link, with the method that made it |
| `tables.csv` | Extracted table records (caption, headers, rows) |
| `figures.csv` | Figure captions and cross-references to materials/properties/tables |
| `equations.csv` | Extracted equations with type, variables, and context sentence |
| `workflow.csv` | Ordered experimental/computational workflow steps per paper |
| `database.xlsx` | All of the above as sheets in one workbook |
| `database.json` | All of the above as nested JSON, one record per paper |
| `database_summary.csv` | Flat, one-row-per-paper legacy summary for quick scanning |

Every table only has columns that apply to each of its rows. So an empty cell — written `NONE` —
always means *looked for and not found in the paper*, never *does not apply*. (The one exception
is `transport_component`, which only applies to ion-transport properties and reads `n/a` for the
others.) **`activation_energy.csv` has no empty cell at all**: what a paper leaves unsaid about an
activation energy is answered with the likeliest value and marked as assumed — see
[No open answer for an activation energy](#no-open-answer-for-an-activation-energy).

### One activation energy

Papers call the energy barrier of an ion hop many things. Here they are **one property**,
`Activation_Energy`, always in eV, and `activation_energy.csv` lists it in a single numeric column,
`activation_energy_eV`, so the table sorts, filters and plots as it is. The paper's own word is
kept next to it in `reported_as`:

| The paper says | `activation_energy_eV` | `reported_as` |
|---|---|---|
| "an activation energy of 0.30 eV" | 0.3 | `activation energy` |
| "Ea = 250 meV", "E_a of …", "an Em of …" | 0.25 | `Ea`, `Em` |
| "a migration barrier of 0.27 eV" — and hopping, diffusion, energy, activation … barrier, "a barrier of only …", "a 0.27 eV barrier" | 0.27 | `migration barrier`, `energy barrier`, `barrier`, … |
| "a migration energy of 0.31 eV", "activation enthalpy" | 0.31 | `migration energy`, … |
| "an activation energy of 31.2 kJ mol−1" | 0.3234 | `activation energy` (kJ/mol and kcal/mol are converted to eV per ion) |
| "the activation energy for the reorientation of the PS4 groups is 0.40 eV" | 0.4 | `activation energy (of a rotation)` — kept, and marked, because it is not the barrier of the mobile ion |

An energy is *not* taken for an activation energy when the quantity named last before it is
another one — a band gap, a formation energy, an energy above the hull, a Hubbard U, the error of a
model — or when its unit is per atom or per length (`25 meV/atom`, `0.01 eV/Å`); nor is a Schottky
or tunnelling barrier. An activation energy is a property of a material, so only values tied to a
material are in this table; the others are in `unassigned_values.csv` (or dropped, when the run
asks for `require_material`).

### Value context

`properties.csv`, `activation_energy.csv` and `unassigned_values.csv` (and the matching sheets and
JSON records) describe each value with the same columns.

**Where the value was read**

| Column | Meaning |
|---|---|
| `extracted_from` | The part of the paper the value was read from: `Text` (running text), `Table` (a table cell) or `Figure` (the caption of a figure; the points plotted in the image are not read). It stands right after the value, with the page |
| `page` | The page of the PDF it is on |
| `source` | The same in words: `Text`, `Text, citing Figure 4b` (the sentence points to a figure or table), `Figure 3 caption`, `Table 2, row: LLZO \| column: Ea (eV)` |
| `section`, `sentence` | The paper section and the verbatim sentence (the caption, for a table cell) |

**What the value is for**

| Column | Meaning |
|---|---|
| `material_id`, `material_formula` | The material the value was obtained for, in one spelling per composition (elements from the least to the most electronegative: `Li6PS5Cl`, `Li10GeP2S12`, `Na3V2(PO4)3`). The general formula of a series stays one (`Li3-xY1-xZrxCl6`) unless its sentence fixes x (`x = 0.5` → `Li2.5Y0.5Zr0.5Cl6`) or gives one value for each x ("3.9 mS/cm for x = 0.25 and 7.5 mS/cm for x = 0.6": one member each); a mixture keeps its parts (`0.8Li2O-ZrCl4`, `70Li2S-30P2S5`) |
| `material_link` (`extraction_method` in `relations.csv`) | How the value was tied to that material — see the list below |
| `composition` | Element amounts of that material, elements in alphabetical order, e.g. `{"Cl": 1.0, "Li": 6.0, "P": 1.0, "S": 5.0}` |
| `structure` | Crystal system, structure family, polymorph, glass/amorphous state and space group, e.g. `cubic \| garnet \| Ia-3d`. Where neither the paper nor the composition gives any of these, the kind of compound instead: `thiophosphate`, `chloride`, `oxide`, `phosphate`, `borohydride` … (`basis` says so) |
| `ionic_radii` | Shannon ionic radius (Å) of each ion of the material, e.g. `{"Li+": 0.76, "La3+": 1.032, "Zr4+": 0.72, "O2-": 1.4}`. Computed from the composition, not read from the paper: charge-balanced oxidation states, six-fold coordination (nearest tabulated one otherwise), high spin. The key shows the oxidation state that was assumed. Radii a paper quotes itself are extracted as the `Ionic_Radius` property |

**Under which conditions**

| Column | Meaning |
|---|---|
| `temperature` | In kelvin (`298.1 K`), `room temperature` when the paper gives no number, or — for an activation energy, which is the slope over a range — the range it was fitted over (`300-700 K`). `0 K` for a static (NEB, bond-valence) barrier. Processing temperatures ("sintered at 1200 °C") are not conditions |
| `pressure` | In GPa (`0.005 GPa` for a 5 MPa stack pressure) or `ambient pressure`. Only a pressure of the measurement counts — a bare "10 GPa" is usually a modulus, and "cold-pressed at 300 MPa" is how the pellet was made |
| `data_origin` | `experimental` or `simulation` (DFT, AIMD/MD, NEB, ML predictions, …); `unspecified` when nothing establishes it (never for an activation energy) |
| `transport_component` | For activation energies, ionic conductivities and diffusion coefficients: `bulk`, `grain_boundary`, `surface` or `total`; `unspecified` when nothing establishes it (never for an activation energy). "The total and bulk conductivities are 0.4 and 2.5 mS/cm" gives each value its own, in that order |
| `attribution` | `this work` for a result of the paper itself, `cited` for one it quotes from another source ("Kamaya et al. reported …", "… 12 mS/cm [5]", every value of a review) |
| `n_assumed` | How many of the five answers (structure, temperature, pressure, origin, component) are defaults rather than read from the paper: sort by it to see the best-documented rows first |
| `basis` | Where each of those answers comes from — see next |

### Where each answer comes from: `basis`

A value's own sentence usually leaves most of its context out: a paper says once, in its methods,
that the impedance was measured from 25 to 100 °C, and then quotes activation energies without
repeating it. So each part of the context is looked for level by level, from the value's own
sentence outwards, and `basis` records for each the level it was found at:

```
structure: paper + known for this composition | temperature: paper ("AIMD simulations were run at
600 K, 800 K, 1000 K …") | pressure: assumed (no pressure is stated) | origin: stated (AIMD) |
component: assumed (simulated in a bulk cell)
```

| Level | Meaning |
|---|---|
| `stated` | In the value's own sentence, in the wording tied to that value (a condition that sits closer to another value belongs to that value) |
| `context` | In the sentences just before it |
| `caption of Figure 3` | In the caption of the figure or table the sentence points to (the panel it names, where the caption can be split by panel) |
| `table` | In the value's row, its column header or the table's caption |
| `paper` | Stated once for the whole study: the temperature range of its impedance measurements or of its molecular-dynamics runs, the stack pressure of its measurements, the structure it gives the material elsewhere — and, for a paper that only computes or only measures, that its own results are simulated or experimental. Only applied to the paper's own results (`attribution` = `this work`) for the materials it studies, never to a value it quotes |
| `known for this composition` | (`structure` only) The structure family that follows from the composition when the paper names none: Li7La3Zr2O12 and its doped variants are garnets, Li6PS5X argyrodites, A(1+x)M2(PO4)3 NASICONs, Li10GeP2S12 LGPS-type, plus perovskite (LLTO), anti-perovskite, olivine, spinel, layered oxides, rock-salt and anti-fluorite binaries. Nothing is named where the composition leaves a doubt (Li3PS4, the halides Li3MX6) |
| `assumed` | A convention, with its reason in brackets — see below |
| `not stated` | Nothing in the paper establishes it: the cell is `NONE` / `unspecified`. Never for an activation energy, where a default answers instead — see [below](#no-open-answer-for-an-activation-energy) |

The conventions, all marked `assumed` so that they can be filtered out:

- **Pressure** — `ambient pressure` when the paper states none (not in a paper where pressure is one of the variables).
- **Transport component** — a simulated value is a `bulk` one (not in a paper about grain boundaries, nor when the sentence speaks of a surface or an interface); a measured conductivity or activation energy is the `total` of the pellet, bulk and grain boundaries together, unless the wording says which part it is; an NMR value is a `bulk` one.
- **Temperature** — `0 K` for a static calculation; `room temperature` for a conductivity or diffusion coefficient given without one, in a paper where those that do have a temperature are (at least 3 of them, and 70%) at room temperature.
- **Origin** — a quoted conductivity is a measured one unless its sentence calls it computed.

To keep only what the paper itself states, drop the rows (or ignore the cells) whose `basis` says
`assumed` for the column you use; `n_assumed` counts them per row.

### No open answer for an activation energy

An activation energy with a hole in its row cannot be filtered or compared, so for this one
property nothing is left `NONE` or `unspecified`. After every level above has been tried, what is
still open is answered with the likeliest value — and says `assumed`, with the reason:

| Still open | Answered with |
|---|---|
| origin | `simulation` for a value of a computational paper, `experimental` for one of an experimental paper; otherwise by what the value is called: a *migration / diffusion / energy barrier* or a *migration energy* is usually computed, an *activation energy* or *activation barrier* usually measured |
| transport component | `bulk` for a computed value (and for an NMR one, and for the rotation of an anion group), `total` for a measured one |
| temperature | `0 K` for a computed barrier (a static calculation, unless its own sentence speaks of dynamics or of a fit); the range the paper gives for its own runs or measurements, for its own values; else `600-1200 K`, the usual range of molecular-dynamics runs, for a simulated activation energy, and `room temperature`, around which measured ones are fitted |
| pressure | `ambient pressure` |
| structure | the kind of compound, from its composition (not an assumption, but not a crystal structure either) |

These are defaults, not statements of the paper. On 208 solid-electrolyte papers they are a large
part of the table: 72% of the temperatures, 91% of the transport components, 99% of the pressures
and 23% of the origins are assumed, and for 27% of the rows the structure is only the kind of
compound. Every row has its `basis`, and `n_assumed` says how many of its answers are defaults.
The other properties (conductivities, diffusion coefficients, …) are not completed this way: for
them `NONE` still means that the paper does not say.

### How materials are found and tied to values

`material_link` says how a value was tied to its material:

| Link | Meaning |
|---|---|
| `apposition` | The value stands right next to the material: "0.31 eV (LLZO)", "LLZO (0.31 eV)", "0.38 eV for Li6PS5Cl, 0.36 eV for Li6PS5Br" |
| `named_with_quantity` | "the activation energy of LLZO is 0.30 eV, lower than that of LATP" |
| `proximity` | The only material the sentence names — or, where it gives several values, the one material named since the value before: "Li3InCl6 can reach 1.49 mS/cm, and Li3YBr6 can reach 1.7 mS/cm" |
| `dependency_parse` | Several materials in the sentence; the one grammatically closest to the value |
| `list_alignment` | "A, B and C … 0.6, 1.2 and 1.5 eV, respectively": the lists are paired off. Also "A and B, with σ = 82 mS/cm (Ea = 0.17 eV) and σ = 177 mS/cm (Ea = 0.11 eV)": materials named together, then as many values, in the same order |
| `table_row`, `table_caption` | The material of the value's table row; or of the caption, for a table with no material column |
| `previous_sentence` | The sentence names no material but refers back to one: "Its conductivity …", "… in the γ-phase …" |
| `paragraph_topic` | (activation energies in running text only) the material the previous sentences are about, when it is one of the paper's main materials. The weakest link: check these rows first |

- *The paper's own names.* A formula defined in brackets — `Na3Zr2Si2PO12 (NZSP)` — is recognised
  under that name for the rest of the paper, also with a tag that only says how the sample was made
  (`BM-LYC`, `c-LLZO`). A name with a composition hung on it (`XYZ-NZSP`, `LPS-0.05SnO2`,
  `Ta-LLZO`) is another sample and is never taken for the base compound.
- *Common abbreviations* (LLZO, LATP, LAGP, LLTO, LGPS, LiPON, NASICON, NMC811, …) stand for the
  composition they are usually written for; `is_known_alias` marks them in `materials.csv`.
- *Not a material.* Acronyms that spell element symbols (LiTFSI, PVDF), building blocks of a
  structure (PO4 units, LiS4 tetrahedra, PS4³⁻ anions), a reference electrode ("vs. Na2Sn"), and a
  formula a table lost the subscripts of. A citation number run into a formula is cut off
  (`Li6PS5Cl8` → `Li6PS5Cl`).
- *Not the material of the value.* A filler, an additive or an electrode named in the sentence
  ("with 1 wt% MgF2 additive", "stable against lithium metal"); the filler or the salt of a
  composite or polymer electrolyte ("LLZTO@PEO", "the electrolyte containing …", "PEO–LiClO4");
  what a comparison names ("Similar to the β-Li3PS4 results, the activation energy (0.67 eV) …",
  "… surpassing that of the Hf-substituted Li2.6Yb0.6Hf0.4Cl6") — the mention that is compared
  with, so two forms of one compound can still be told apart ("β-LZC shows a lower barrier
  (0.68 eV) than α-LZC (0.97 eV)"); and the material named before another value when a variant is
  named in between ("Li6PS5Cl shows 3 mS/cm, whereas the Br-substituted sample shows 5 mS/cm":
  the second value is left without a material).
- *Lists.* Every value of a list is its own row — "0.6, 1.2 and 1.5 eV", "0.30 eV for A and
  0.45 eV for B", both ends of "0.23–0.39 eV". With several materials in the sentence a value is
  tied to one only if it stands next to it or the lists are paired off ("…, respectively");
  otherwise it is left without a material rather than guessed.
- *Numbers as PDFs print them.* A conductivity or a diffusion coefficient is read with its power
  of ten in every shape it comes out of a PDF: `10−13 S cm−1`, `10- 4`, `1.06×10 –4`, `5·10−9` and
  `5.10-9` (a point for the multiplication sign), `3.8 × 10−10 ± 1.1 × 10−10`. The numbers of a
  range or a list share the power of the last one (`1–2 × 10−4 S/cm` is 1 and 2 × 10⁻⁴), and a
  bare `10–20` is a power of ten in S/cm but a range in mS/cm.
- *Not a result.* A number is not reported when its wording shows it is something else: a
  threshold (`<0.3 eV`, "above 1 mS/cm"), an assumed or typical value, an upper limit, the error of
  a model (`RMSE of 0.15 eV`), a change or a difference ("lowered by 0.1 eV", "0.2 eV higher
  than"), the thermal energy (`kBT = 78 meV`), a reference line in a plot or the tick labels of a
  plot that PDF extraction ran together. Run with `-v` to see each skipped value and why.

The flat summary CSV carries the same information for each property's best candidate as
`*_SourceType`, `*_Source`, `*_Page`, `*_Material`, `*_Temperature`, `*_Pressure`, `*_Origin`
and `*_Type` (the transport component).

### A database made by an earlier version

The tables of this version have other columns than before (one activation-energy property instead
of two, `basis`, `extracted_from`, `n_assumed`, the split into `properties` / `unassigned_values`
/ `methods`). New papers cannot be added to an older database, and the program says so instead of
mixing the two. Extract everything again with `--rebuild`:

```bash
python main.py both --job configs/sse.yaml --stage extract --rebuild   # web papers + your own PDFs
python main.py local --rebuild                                          # your own PDFs only
```

Nothing is downloaded again and nothing is deleted: the previous files are moved to a
`previous_<date>/` folder inside the results folder. (A database in the `output/` folder of an
earlier version is simply left where it is: the results now go to `local_output/` and
`web_output/`.)

## Known limitations

Checked by running the pipeline end to end on 208 solid-electrolyte papers (23 supplied PDFs and
185 fetched by the web project) and reading random samples of the result against the sentences
they came from:

- **Extraction is rule-based, not perfect.** In random samples of 40 rows of
  `activation_energy.csv` read against their sentences, the value and the material it is tied to
  were right in 8 to 9 rows out of 10. The usual mistakes: a value of a doped or otherwise modified
  sample tied to the base compound; a value tied to the paragraph's material when the sentence was
  about another one (`material_link` = `paragraph_topic` is the weakest link — sort by it to check
  those first); a sentence that PDF extraction ran together with a neighbouring table or caption.
  Treat `confidence` as a filter, not a guarantee, and spot-check anything used downstream: every
  row carries its sentence.
- **A full row is not a fully documented one.** `activation_energy.csv` has no empty cell, but
  much of what fills it is a default, not something the paper says: on those 208 papers, 72% of
  the temperatures, 91% of the transport components, 99% of the pressures and 23% of the origins
  are assumed, and 27% of the structures are only the kind of compound — typically for a value
  quoted from another source, whose conditions are in that source. Every row has at least one
  such answer (most have two or three). `basis` marks each of them `assumed`, with its reason, and
  `n_assumed` counts them: filter on these before drawing a conclusion from a condition column.
- **A value whose material cannot be established is not guessed.** With `require_material: true`
  (the web job's default) it is dropped; without it, it goes to `unassigned_values.csv`. This is
  the price of tying fewer values to a wrong material.
- **Experimental or simulated, for a paper that does both**, is only known where the wording says
  so. A paper is called computational or experimental as a whole when the vocabulary of the other
  kind is all but absent from it.
- **Values inside a figure are not read.** `Figure` means the value stands in the figure's
  caption; data points plotted in the image itself are not digitised. In experimental papers most
  activation energies are in Arrhenius plots and tables, so the text often holds one or two.
- **Table extraction can misfire on complex PDF layouts.** pdfplumber sometimes extracts
  non-tabular page content (e.g. multi-column figure text) as a spurious table with empty rows,
  and often loses the subscripts of the formulas in a real one, which then cannot be read as
  materials. A table pdfplumber does not recognise is still read as text, so its values are
  reported with `extracted_from` = `Text`; a table whose caption was not found is labelled just `Table`.
- **A material is a formula.** A polymer or composite electrolyte named only by an acronym
  (PEO–LiTFSI, "PPS-QSSE"), a sample label the paper never defines by a formula ("NLZC0.2-HT") and
  a family written with a placeholder (`Li3MX6`) are not resolved; their values are in
  `unassigned_values.csv`. A doped sample named by a label built on a known name (`Ta-LLZO`) is
  left unresolved rather than given the base compound's composition.
- **Ionic radii assume one oxidation state per element**, the one that balances the formula; for a
  mixed-valence compound the key of each radius shows which was assumed.
- **The web project reads only what it may.** A paper with no open copy (and, for Elsevier or
  Wiley, no key or no entitlement from where you run) is marked `closed` and needs a manual PDF.
  Many publishers' servers answer a scripted download of even an open-access paper with 403; that
  is respected, and another lawful copy is the way round it: the publisher's API (with its free
  key), PubMed Central, a repository, a preprint. If Elsevier's API only returns a paper as XML,
  it is not extracted yet — a reader for it is the next step.
- **Screening works from the title and abstract**, so a paper whose abstract does not mention the
  property is not proposed (the `why` column shows what scored). Reviewing the list is the
  safeguard; `--yes` removes it.
- **OCR quality depends on Tesseract being installed** (`brew install tesseract` /
  `sudo apt install tesseract-ocr`); without it, image-only/scanned pages silently fall back to
  the (near-empty) native text layer instead of erroring.
- **The ranking is only as good as the extraction.** It sorts what parts 1 and 2 found, so a value
  tied to a wrong material is ranked as that material. The `checks` column shows where the values
  of a material disagree, and every value keeps its paper, page and sentence: read those of any
  material you rely on. An activation energy is also a default-filled row (see
  [No open answer for an activation energy](#no-open-answer-for-an-activation-energy)): a computed
  and a measured barrier of one material are both in its group unless you filter with `--origin`.

## Project structure

```
AutoMatExtract/
├── main.py          # The terminal gate: local | web | both | gui
├── gui/             # The window gate: app (the frame), local_panel, web_panel, dialogs, results, widgets
├── database.py      # Reads the database back as tables (the window's previews)
├── pipeline.py      # Orchestrates parsing → extraction → ranking → export
├── parser.py        # PyMuPDF/pdfplumber: text, tables, sections, references
├── ocr.py           # OpenCV preprocessing + Tesseract OCR for scanned pages
├── extractor.py     # SpaCy NLP, regex matching, PyMatgen integration
├── normalizer.py    # Scientific value & unit normalization/conversion
├── chemistry.py     # Materials: formulas, abbreviations, ionic radii, structure families
├── quantities.py    # The transport values of a sentence (activation energy, conductivity, diffusion)
├── transport.py     # Bulk / grain-boundary / surface / total typing of transport values
├── context.py       # Temperature, pressure, experiment-vs-simulation and structure of a value
├── study.py         # What a paper states once for all its values (kind of study, conditions)
├── web/             # Project 2: sources/ (OpenAlex, arXiv), screening, resolve + fetch, elsevier, wiley, ledger, harvest
├── configs/         # Job files for the web project (sse.yaml)
├── tests/           # Offline tests: test_extraction.py (what is read from text), test_web.py (the web project), test_gui.py (the window)
├── ranking.py       # Deduplication and confidence scoring
├── exporter.py      # CSV / Excel / JSON generation
├── models.py        # Shared dataclasses (PaperData, Material, ExtractedField, ...)
├── config.py        # Regex patterns and NLP context lists
├── requirements.txt
├── papers/          # Default input directory for PDFs (papers/web/: fetched by the web project)
├── local_output/    # The database of the local articles (python main.py local)
├── web_output/      # The database of the web articles (python main.py web)
└── SelectingTopMaterial/   # Part 3: ranks the materials of both databases (python -m SelectingTopMaterial)
    ├── criteria.toml       # The classes and their limits — edit this to change the rule
    ├── criteria.py         # Which class an energy belongs to; reads and checks criteria.toml
    ├── loader.py           # Reads activation_energy.csv + papers.csv of each folder; each paper once
    ├── selection.py        # Groups values by material, picks one Ea per material, ranks
    ├── models.py           # A value, a ranked material, the whole ranking
    ├── console.py          # What the terminal shows
    ├── exporters.py        # CSV, Excel, JSON
    ├── html_report.py      # report.html (data written into report_template.html)
    ├── palette.py          # The colours of the classes
    ├── cli.py              # The command line (python -m SelectingTopMaterial)
    ├── tests/              # Offline tests on made-up databases
    └── results/            # What it writes (top_materials.csv, report.html, ...)
```

## Contributing

Contributions are welcome.

1. Fork the repo and create a feature branch.
2. Keep changes focused — the pipeline stages (`parser` → `extractor` → `ranking` → `exporter`)
   are intentionally decoupled, so a change to one stage shouldn't need to touch the others.
3. Preserve the "strict defaults" convention used throughout the codebase: missing/unparsed
   values are represented as `"NONE"` (or `ExtractedField.empty()`), not `None` or omitted keys,
   so downstream exports stay schema-consistent.
4. Test against a small set of real PDFs in `papers/` and check the generated files in `local_output/`
   before opening a PR.
5. Open a pull request describing the change and, if it affects extraction quality, include a
   before/after comparison on a sample paper.

Bug reports and feature requests are welcome via GitHub issues.

## License

No license file is currently included in this repository. Contact the maintainer before reusing
this code outside of personal/evaluation purposes.
