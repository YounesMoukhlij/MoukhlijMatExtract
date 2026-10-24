# MoukhlijMatExtract (MME)

**Author:** Younes Moukhlij — Software Engineering student at 1337 Coding School, PhD researcher at FPK, USMS.

MME reads scientific papers on **solid-state electrolytes**, extracts their activation energies,
conductivities and other properties into databases, **ranks** the materials and **classifies**
them by structure.

```
your PDFs ─▶ 1 · LocalExtraction ─▶ local_output/ ─┐
                                                    ├─▶ 3 · SelectingTopMaterial ─▶ results/
the web ───▶ 2 · WebScraping ─────▶ web_output/ ───┤
                                                    └─▶ 4 · Crystal and Structure Classification ─▶ one database per class
```

## The folders

| Folder | What it does | Docs |
|---|---|---|
| **`LocalExtraction/`** — part 1 | Extracts the data of your own PDFs into a database | [README](LocalExtraction/README.md) |
| **`WebScraping/`** — part 2 | Finds papers online, downloads the legal copies and extracts them the same way | [README](WebScraping/README.md) |
| **`SelectingTopMaterial/`** — part 3 | Ranks the materials by activation energy | [README](SelectingTopMaterial/README.md) |
| **`Crystal and Structure Classification/`** — part 4 | Sorts the materials by crystal family and by structure family | [README](<Crystal and Structure Classification/README.md>) |
| `Fetch_DOIs/` — side tool | Collects the DOIs of papers on a topic into a CSV | [below](#fetch_dois) |
| `younes4scraping/` — side tool | Downloads the PDF of a DOI | [README](younes4scraping/README.md) |
| `configs/` | The job file `sse.yaml`: what parts 2 and `Fetch_DOIs` search for | |

Parts 1 and 2 make the databases; parts 3 and 4 read them. The side tools are not part of this
chain.

## Install (once)

You need **Python 3.11+** and, for scanned pages, **Tesseract** (`brew install tesseract` on macOS,
`sudo apt install tesseract-ocr python3-tk` on Debian/Ubuntu,
[installer](https://github.com/UB-Mannheim/tesseract/wiki) on Windows).

The whole project works inside **one virtual environment (venv)**, `.venv/` in the project folder.
From the project folder:

```bash
python3 -m venv .venv                     # create the venv
source .venv/bin/activate                 # enter it (Windows: .venv\Scripts\activate)
pip install -r requirements.txt           # install the packages inside it
python -m spacy download en_core_web_sm   # and the language model
```

Or just `make install`. Then **work inside the venv**: enter it in every new terminal
(`source .venv/bin/activate`); your prompt starts with `(.venv)`.

## Quick start

From the project folder, inside the venv:

```bash
python -m LocalExtraction                         # 1. the PDFs of LocalExtraction/papers/ → a database
python -m WebScraping                             # 2. papers from the web → a database
python -m SelectingTopMaterial                    # 3. rank the materials
python "Crystal and Structure Classification"     # 4. classify them
```

Add `gui` after any of them for a window. The same as shortcuts:

| | |
|---|---|
| `make local` · `make web` · `make rank` · `make classify` | the four parts |
| `make local-gui` · `make web-gui` · `make rank-gui` · `make classify-gui` | their windows |
| `make doi` | the `Fetch_DOIs` side tool |
| `make install` · `make test` · `make clean` | set up · run every test · remove `__pycache__/` |

## The four parts

**1 · LocalExtraction.** Put your PDFs in `LocalExtraction/papers/` and run it. It reads the new
PDFs (text, tables, figures, scanned pages), finds the materials and their values, and writes
`LocalExtraction/local_output/`: one CSV per quantity (`activation_energy.csv`,
`ionic_conductivity.csv`, …), `materials.csv`, `papers.csv` and more, plus `database.xlsx`. No cell
is left empty: the `basis` column says whether each answer was stated, inferred or assumed.

**2 · WebScraping.** Searches 14 services (OpenAlex, arXiv, Crossref, Semantic Scholar, …) with the
queries of `configs/sse.yaml`, keeps the papers whose title and abstract match, downloads the legal
copies into `WebScraping/papers/`, and extracts them into `WebScraping/web_output/` (the same files
as part 1). Running it again only does what is new. Your e-mail and the API keys (all free, all
optional) go in `WebScraping/.env`; `python -m WebScraping --check` tests them.

**3 · SelectingTopMaterial.** Takes one activation energy per material and sorts the materials into
**Superionic** (< 0.25 eV), **Performant** (< 0.30), **Acceptable** (< 0.40) or Rejected. Writes
`SelectingTopMaterial/results/` (`top_materials.csv`, `selection.xlsx`, `report.html`, …). The
limits are in `criteria.toml`; filters such as `--element Na` or `--origin experimental` narrow the
ranking.

**4 · Crystal and Structure Classification.** Puts each material in its structure family (oxide,
sulfide, halide, …) and, when it has one, its crystal family (NASICON, garnet, argyrodite, …). It
writes one database per class into `crystal_structure/` and `structure_families/`, each split into
`bulk/`, `grain_boundary/` and `total/`, plus `all_materials.csv`. Part 3 can rank one class:
`python -m SelectingTopMaterial --source "Crystal and Structure Classification/crystal_structure/garnet"`.

## Side tools

### Fetch_DOIs

Searches OpenAlex, Crossref, Semantic Scholar, arXiv and Google Scholar and adds one row per DOI to
`Fetch_DOIs/dois.csv`. Each run adds to it.

```bash
python Fetch_DOIs/get_dois.py                              # the queries of configs/sse.yaml
python Fetch_DOIs/get_dois.py "LLZO garnet" --no-scholar   # your own keywords, without Google Scholar
```

### younes4scraping

`younes4scraping/fetched articles/`. It needs Google Chrome and its own packages, in the same venv.
Unlike part 2 it does not only fetch legal copies: check your institution's rules first.

```bash
pip install -r younes4scraping/requirements.txt   # once, inside the venv
python younes4scraping/run.py 10.1038/nature14539
```

## Keeping it up to date

| You did | Run |
|---|---|
| Added PDFs to `LocalExtraction/papers/` | part 1, then parts 3 and 4 |
| Want more web papers | part 2, then parts 3 and 4 |
| Updated the program | parts 1 and 2 with `--rebuild` (part 2: `--stage extract --rebuild`), then 3 and 4 |
| Changed the ranking limits | part 3 |

A rebuild never deletes: the old files are moved to `previous_<date>/` inside the output folder.

## Not in git

The articles (every PDF) and everything the programs write (`local_output/`, `web_output/`,
`results/`, `crystal_structure/`, `structure_families/`, `all_materials.csv`, `dois.csv`) stay on
your computer. A fresh copy has no database: add PDFs and run part 1 or 2 first, then parts 3 and 4.

Keep the folders side by side: part 2 uses part 1's extraction code, and part 4 its chemistry.

## License

No license file yet. Contact the author before reusing this code beyond personal or evaluation use.
