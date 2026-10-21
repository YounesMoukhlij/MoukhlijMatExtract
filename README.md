# MoukhlijMatExtract (MME)

**Author:** Younes Moukhlij — Software Engineering student at 1337 Coding School, PhD researcher at USMS.

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
| **2 · WebScraping** | `python -m WebScraping` | a job file (`WebScraping/configs/sse.yaml`) and the web | `WebScraping/papers/` (the PDFs), `WebScraping/web_output/` |
| **3 · SelectingTopMaterial** | `python -m SelectingTopMaterial` | `local_output/` and `web_output/` | `SelectingTopMaterial/results/` |
| **4 · Crystal and Structure Classification** | `python "Crystal and Structure Classification"` | `local_output/` and `web_output/` | its `crystal_structure/`, `structure_families/`, `all_materials.csv` |

Run every command **from the project folder** (`python3` where `python` is not found). Each part
also has a window: add `gui` after its command (`python -m LocalExtraction gui`, …).

## Install (once)

```bash
# 1. Tesseract, for scanned pages
brew install tesseract                 # macOS
sudo apt install tesseract-ocr         # Debian/Ubuntu (also: sudo apt install python3-tk for the windows)
# Windows: https://github.com/UB-Mannheim/tesseract/wiki

# 2. The Python packages and the language model
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

Python 3.9+ for parts 1 and 2, **3.11+** for parts 3 and 4.

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
| `materials.csv` · `papers.csv` · `summary.csv` | material · paper · paper, in one line (its materials, how many values of each kind) |
| `methods.csv` · `relations.csv` · `tables.csv` · `figures.csv` · `equations.csv` · `workflow.csv` | setting of the study · material ↔ value link · table · figure · equation · step of the work |
| `database.xlsx` · `database.json` | all of it as one workbook · nested per paper |

**No cell is left open.** What the paper does not say is answered with the likeliest value — the
`basis` column of each row says, for every answer, whether it was stated, read nearby, given by the
paper as a whole, or assumed (and why). → [More](LocalExtraction/README.md)

## 2 · WebScraping — papers from the web

```bash
python -m WebScraping
```

One command does it all: it searches OpenAlex, arXiv, Crossref and up to eleven other indexes with the queries of
`WebScraping/configs/sse.yaml`, keeps the papers whose title and abstract score, downloads the legal
copies into `WebScraping/papers/`, and extracts them (with part 1's code) into
**`WebScraping/web_output/`** — the same files as above. Run it again and it carries on: nothing is
downloaded twice.

| Option | |
|---|---|
| `--job FILE` | Another job file (what to search for, which papers to keep, what to extract) |
| `--limit N` | Download at most N papers in this run |
| `--check` | Test the setup (network, API keys, folders) and stop |
| `--stage extract` | Only extract what is already downloaded |

To check the list before anything is downloaded, set `review: true` in the job file: the command
then stops after the search, you set `decision` in `WebScraping/papers/candidates.csv`, and
`python -m WebScraping --stage fetch` goes on. Optional keys (Elsevier, Wiley) and your e-mail go in
`WebScraping/.env`. → [More](WebScraping/README.md)

## 3 · SelectingTopMaterial — the best materials

```bash
python -m SelectingTopMaterial
```

It reads `activation_energy.csv` (and `papers.csv`) of both databases, takes one activation energy
per material and sorts the materials into **Superionic** (Ea < 0.25 eV), **Performant** (< 0.30),
**Acceptable** (< 0.40) or Rejected, and writes **`SelectingTopMaterial/results/`**:
`top_materials.csv`, `all_materials.csv`, `values.csv`, `selection.xlsx`, `selection.json`,
`report.html`. Options: `--origin experimental`, `--element Na`, `--top 10`, `--open` (the report in
the browser). The classes are in `SelectingTopMaterial/criteria.toml`. → [More](SelectingTopMaterial/README.md)

## 4 · Crystal and Structure Classification — by structure

```bash
python "Crystal and Structure Classification"
```

It reads both databases and puts **every material in one class of each kind** — none is left
unclassified — and writes, inside its folder, **one database per class**:

| Folder | Classes |
|---|---|
| `crystal_structure/` | NASICON, LISICON, thio-LISICON, garnet, argyrodite, LGPS-type, perovskite, anti-perovskite, spinel, Li3YCl6-type, Li3InCl6-type, …, amorphous, glass-ceramic — and, in `composition_types/`, the materials of no named type by their composition type ("A3MX6 halide") |
| `structure_families/` | oxide, sulfide, selenide, halide, oxyhalide, nitride, phosphide, hydride, element_or_alloy |

Each class folder holds the same files as a database (`materials.csv`, `activation_energy.csv`,
`ionic_conductivity.csv`, …, `papers.csv`), so part 3 ranks inside one class too:
`python -m SelectingTopMaterial --source "Crystal and Structure Classification/crystal_structure/garnet"`.
`crystal_structure_basis` says how each material's class was decided. → [More](<Crystal and Structure Classification/README.md>)

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
make local     make web     make rank     make classify     # the four parts
make local-gui make web-gui make rank-gui                    # their windows
make test                                                   # every test (python -m pytest)
```

## Project layout

```
MoukhlijMatExtract/
├── LocalExtraction/                       # Part 1 — code, gui/, tests/, papers/, local_output/
├── WebScraping/                           # Part 2 — code, gui/, tests/, configs/, .env, papers/, web_output/
├── SelectingTopMaterial/                  # Part 3 — code, gui.py, tests/, criteria.toml, results/
├── Crystal and Structure Classification/  # Part 4 — code, tests/, crystal_structure/, structure_families/
├── Makefile
└── requirements.txt
```

The web part uses the extraction code of the local part, and the classification its chemistry, so
keep the folders side by side. The ranking uses neither: it only reads the result folders.

## License

No license file is currently included in this repository. Contact the maintainer before reusing
this code outside of personal/evaluation purposes.
