# MoukhlijMatExtract (MME)

**Author:** Younes Moukhlij — Software Engineering student at 1337 Coding School, PhD researcher at FPK, USMS.

MoukhlijMatExtract (MME) finds the activation energies (and conductivities, diffusion coefficients, …) of
solid-state electrolytes in scientific papers, ranks the materials by them and classifies them by
structure. It has **four parts**. Each one is a folder of its own and runs alone with **one
command**; the first two make the databases the last two read:

```
  your PDFs ──▶ 1 · LocalExtraction ──▶ LocalExtraction/local_output/ ──┐
                                                                         ├──▶ 3 · SelectingTopMaterial ──▶ SelectingTopMaterial/results/
  the web ────▶ 2 · WebScraping ─────▶ WebScraping/web_output/ ─────────┤
                                                                         └──▶ 4 · Crystal and Structure Classification
                                                                                    ──▶ crystal_structure/ + structure_families/
```

| Part | Command | Reads | Writes |
|---|---|---|---|
| **1 · LocalExtraction** | `python -m LocalExtraction` | the PDFs in `LocalExtraction/papers/` | `LocalExtraction/local_output/` |
| **2 · WebScraping** | `python -m WebScraping` | a job file (`configs/sse.yaml`) and the web | `WebScraping/papers/` (the PDFs), `WebScraping/web_output/` |
| **3 · SelectingTopMaterial** | `python -m SelectingTopMaterial` | `local_output/` and `web_output/` | `SelectingTopMaterial/results/` |
| **4 · Crystal and Structure Classification** | `python "Crystal and Structure Classification"` | `local_output/` and `web_output/` | its `crystal_structure/`, `structure_families/`, `all_materials.csv` |

Run every command **from the project folder, inside the project's venv** (see
[Install](#install-once)). Each part also has a window: add `gui` after its command
(`python -m LocalExtraction gui`, …).

A few [side tools](#side-tools) sit next to the four parts. The pipeline does not use them.

## Install (once)

**1. Tesseract**, for scanned pages:

```bash
brew install tesseract                 # macOS
sudo apt install tesseract-ocr         # Debian/Ubuntu (also: sudo apt install python3-tk for the windows)
# Windows: https://github.com/UB-Mannheim/tesseract/wiki
```

**2. A virtual environment (venv), with the packages inside it.** The whole project works inside
one venv, `.venv/` in the project folder, so its packages stay apart from the rest of your
computer. It needs Python **3.11 or newer** (`python3 --version`). From the project folder:

```bash
python3 -m venv .venv                     # create the venv, once
source .venv/bin/activate                 # enter it (Windows: .venv\Scripts\activate)
pip install -r requirements.txt           # install the packages inside it
python -m spacy download en_core_web_sm   # and the language model
```

`make install` does the same: it creates `.venv/` and installs the packages and the model into it.

**3. Work inside the venv.** Enter it in every new terminal before you run anything:
`source .venv/bin/activate` (Windows: `.venv\Scripts\activate`). Your prompt then starts with
`(.venv)`, and `python` is the venv's. `deactivate` leaves it. The `make` shortcuts use the venv by
themselves.

## 1 · LocalExtraction — your own PDFs

Put your PDFs in `LocalExtraction/papers/`, then:

```bash
python -m LocalExtraction
```

It reads the PDFs that are new, completes each paper's title, authors, journal, DOI, year and
license from OpenAlex (add `--offline` not to), and writes **`LocalExtraction/local_output/`**:

| File | One row per |
|---|---|
| `activation_energy.csv` | activation energy (eV), whatever the paper called it — migration barrier, Ea, … |
| `ionic_conductivity.csv` · `electronic_conductivity.csv` · `diffusion_coefficient.csv` | value of that quantity (S/cm, S/cm, cm²/s) |
| `properties.csv` | value of a material, of any property |
| `unassigned_values.csv` | value no material could be found for (a class of materials, a sample label the paper never defines, …) |
| `materials.csv` · `papers.csv` · `summary.csv` | material · paper · paper, in one line (its materials, how many values of each kind) |
| `methods.csv` · `relations.csv` · `tables.csv` · `figures.csv` · `equations.csv` · `workflow.csv` | setting of the study · material ↔ value link · table · figure · equation · step of the work |
| `database.xlsx` · `database.json` | all of it as one workbook · nested per paper |

**No cell is left open.** What the paper does not say is answered with the likeliest value — the
`basis` column of each row says, for every answer, whether it was stated, read nearby, given by the
paper as a whole, or assumed (and why).

Options: `--input DIR` (another PDF folder), `--workers N` (PDFs read at once, default 4),
`--rebuild` (read every PDF again). → [More](LocalExtraction/README.md)

## 2 · WebScraping — papers from the web

```bash
python -m WebScraping
```

One command does it all: it searches OpenAlex, arXiv, Crossref and up to eleven other indexes with the queries of
`configs/sse.yaml`, keeps the papers whose title and abstract score, downloads the legal
copies into `WebScraping/papers/`, and extracts them (with part 1's code) into
**`WebScraping/web_output/`** — the same files as above. Run it again and it carries on: nothing is
downloaded twice.

| Option | |
|---|---|
| `--job FILE` | Another job file (what to search for, which papers to keep, what to extract) |
| `--limit N` | Download at most N papers in this run |
| `--check` | Test the setup (network, API keys, folders) and stop |
| `--stage extract` | Only extract what is already downloaded |
| `--yes` | Approve every proposed paper, with no review |
| `--rebuild` | Extract every downloaded PDF again |

To check the list before anything is downloaded, set `review: true` in the job file: the command
then stops after the search, you set `decision` in `WebScraping/papers/candidates.csv`, and
`python -m WebScraping --stage fetch` goes on.

Your e-mail (`MME_EMAIL`) and the API keys go in `WebScraping/.env`. Every key is free and
optional: a source whose key is missing is skipped, with a line saying so. There are keys for
Elsevier, Wiley, OpenAlex, Semantic Scholar, CORE, Springer Nature, NASA ADS, IEEE and Web of
Science. `python -m WebScraping --check` says which are missing and where to get each one.
→ [More](WebScraping/README.md)

## 3 · SelectingTopMaterial — the best materials

```bash
python -m SelectingTopMaterial
```

It reads `activation_energy.csv` (and `papers.csv`) of both databases, takes one activation energy
per material and sorts the materials into **Superionic** (Ea < 0.25 eV), **Performant** (< 0.30),
**Acceptable** (< 0.40) or Rejected, and writes **`SelectingTopMaterial/results/`**:
`top_materials.csv`, `all_materials.csv`, `values.csv`, `selection.xlsx`, `selection.json`,
`report.html`. Options: `--origin experimental`, `--element Na`, `--component bulk`, `--top 10`,
`--open` (the report in the browser). The classes are in `SelectingTopMaterial/criteria.toml`.
→ [More](SelectingTopMaterial/README.md)

## 4 · Crystal and Structure Classification — by structure

```bash
python "Crystal and Structure Classification"
python "Crystal and Structure Classification" gui     # the same, in a window
```

It reads both databases and puts **every material in its structure family** (oxide, sulfide, …)
and, when it belongs to one, in its **known crystal family** (NASICON, garnet, …). It writes
**one database per class**, inside its own folder:

| Folder | Classes |
|---|---|
| `crystal_structure/` | the known crystal families: NASICON, LISICON, thio-LISICON, garnet, argyrodite, perovskite, anti-perovskite, spinel, olivine, layered, rock-salt, anti-fluorite, amorphous, glass-ceramic |
| `structure_families/` | oxide, sulfide, selenide, halide, oxyhalide, nitride, phosphide, hydride, element_or_alloy |

A material of no known crystal family says so in `all_materials.csv`, and its
`crystal_structure_basis` column says how each material's class was decided.

Each class folder holds the same files as a database (`materials.csv`, `activation_energy.csv`,
`ionic_conductivity.csv`, …, `papers.csv`). It also has **three sub-classes**, one database per
kind of activation energy: `bulk/`, `grain_boundary/` and `total/` (e.g.
`crystal_structure/NASICON/bulk/`). So part 3 can rank inside one class, or one sub-class:

```bash
python -m SelectingTopMaterial --source "Crystal and Structure Classification/crystal_structure/garnet"
python -m SelectingTopMaterial --source "Crystal and Structure Classification/crystal_structure/NASICON/bulk"
```

Each of the two folders also has `summary.csv` (one line per class: its materials, papers, lowest
and median activation energies), `activation_energy_by_component.csv` (the same, per bulk, grain
boundary and total) and one workbook of it all (`crystal_structure.xlsx`, `structure_families.xlsx`).

The window shows the classes and sub-classes as a tree, with their materials and every activation
energy of a material. Its filters: measured or computed, the papers' own results, only the
components the papers state. → [More](<Crystal and Structure Classification/README.md>)

## Keeping it up to date

| You did | Run |
|---|---|
| Added PDFs to `LocalExtraction/papers/` | part 1, then parts 3 and 4 |
| Want more web papers | part 2, then parts 3 and 4 |
| Updated the program | parts 1 and 2 with `--rebuild` (part 2: `--stage extract --rebuild`), then 3 and 4 |
| Changed the classes or limits of the ranking | only part 3 |

A database written by an earlier version is rebuilt by itself: its files are moved to
`previous_<date>/` inside the folder, nothing is deleted, and the PDFs are read again.

## Shortcuts and tests

```bash
make install                                                # create the venv and install everything into it
make local     make web     make rank     make classify     # the four parts
make local-gui make web-gui make rank-gui make classify-gui  # their windows
make doi                                                    # Fetch_DOIs (a side tool, below)
make test                                                   # every test of the four parts (python -m pytest)
```

They run with the venv's Python when `.venv/` exists, even if you have not entered it.

## Side tools

These sit next to the four parts. Nothing in the pipeline calls them, and what they download does
not go into the databases.

**`Fetch_DOIs/get_dois.py` — a list of DOIs.** Searches OpenAlex, Crossref, Semantic Scholar, arXiv
and Google Scholar with the queries of `configs/sse.yaml` (or the keywords you give) and adds one row
per DOI to `Fetch_DOIs/dois.csv`. It uses the keys of `WebScraping/.env` when they are there; none is
needed.

```bash
python Fetch_DOIs/get_dois.py                                  # every query of configs/sse.yaml
python Fetch_DOIs/get_dois.py "LLZO garnet" --no-scholar        # your keywords, without Google Scholar
```

PDF in `younes4scraping/fetched articles/`. It needs Google Chrome and its own packages, installed
in the same venv. Unlike part 2, it does not only fetch legal copies: check your institution's
rules before using it. → [More](younes4scraping/README.md)

```bash
pip install -r younes4scraping/requirements.txt   # once, inside the venv
python younes4scraping/run.py 10.1038/nature14539
```

## Project layout

```
MoukhlijMatExtract/
├── LocalExtraction/                       # Part 1 — code, gui/, tests/, papers/, local_output/
├── WebScraping/                           # Part 2 — code, gui/, tests/, .env, papers/, web_output/
├── SelectingTopMaterial/                  # Part 3 — code, gui.py, tests/, criteria.toml, results/
├── Crystal and Structure Classification/  # Part 4 — code, gui.py, tests/, crystal_structure/, structure_families/
├── configs/                               # job files (sse.yaml): the queries of WebScraping and Fetch_DOIs
├── Fetch_DOIs/                            # side tool — get_dois.py, dois.csv
├── younes4scraping/                       # side tool — run.py, its own requirements.txt and README
├── .venv/                                 # the venv (you create it; not in git)
├── Makefile
├── pytest.ini                             # make test: the tests of the four parts
└── requirements.txt
```

The web part uses the extraction code of the local part, and the classification its chemistry, so
keep the folders side by side. The ranking uses neither: it only reads the result folders.

**Not in git:** the articles (every PDF, `LocalExtraction/papers/`, `WebScraping/papers/`) and
everything the programs write (`local_output/`, `web_output/`, `results/`, `crystal_structure/`,
`structure_families/`, `all_materials.csv`, `Fetch_DOIs/dois.csv`). A fresh copy of the project has
no database: put your PDFs in `LocalExtraction/papers/` and run part 1 (or part 2), then parts 3
and 4.

## License

No license file is currently included in this repository. Contact the maintainer before reusing
this code outside of personal/evaluation purposes.
