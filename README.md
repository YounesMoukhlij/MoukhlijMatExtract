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
| **`WebScraping/`** — part 2 | Finds papers online and extracts them — **two methods, one database** (see below) | [README](WebScraping/README.md) |
| **`SelectingTopMaterial/`** — part 3 | Ranks the materials by activation energy | [README](SelectingTopMaterial/README.md) |
| **`Classification/`** — part 4 (Crystal & Structure Classification) | Sorts the materials by crystal family and by structure family | [README](Classification/README.md) |
| `mme_gui/` | The one project window (`make gui`) — a button for each part | |
| `configs/` | The job file `sse.yaml`: what part 2 searches for | |

Parts 1 and 2 make the databases; parts 3 and 4 read them. Inside `WebScraping/` the two methods —
`averageScrap/` (open-source search) and `Fetch_DOIs/` + `moukhlij4scraping/` — both write into
`WebScraping/papers/` and `WebScraping/web_output/`.

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

**Install it as a package** (optional) to get the `mme-*` commands anywhere, from inside the venv:

```bash
pip install -e .            # editable install; add ".[scrape]" for web method 2 (needs Google Chrome)
python -m spacy download en_core_web_sm
```

This adds `mme-gui`, `mme-local`, `mme-web`, `mme-rank`, `mme-classify` and `mme-dois`.

## Quick start

**The whole project in one window:** `make gui` (or `python -m mme_gui`) — a hub with a button for
each part; each opens in its own window. Run the parts left to right.

Or from the terminal, inside the venv:

```bash
python -m LocalExtraction                         # 1. the PDFs of LocalExtraction/papers/ → a database
python -m WebScraping                             # 2. papers from the web → a database
python -m SelectingTopMaterial                    # 3. rank the materials
python -m Classification                          # 4. classify them
```

(After `pip install -e .` these are also `mme-local`, `mme-web`, `mme-rank`, `mme-classify`.)
Add `gui` after any one part for just its window. The same as shortcuts:

| | |
|---|---|
| `make gui` | the one window for the whole project |
| `make local` · `make web` · `make rank` · `make classify` | the four parts |
| `make local-gui` · `make web-gui` · `make rank-gui` · `make classify-gui` | their windows |
| `make doi` | web method 2, step 1 (collect DOIs) |
| `make install` · `make test` · `make clean` | set up · run every test · remove `__pycache__/` |

## The four parts

**1 · LocalExtraction.** Put your PDFs in `LocalExtraction/papers/` and run it. It reads the new
PDFs (text, tables, figures, scanned pages), finds the materials and their values, and writes
`LocalExtraction/local_output/`: one CSV per quantity (`activation_energy.csv`,
`ionic_conductivity.csv`, …), `materials.csv`, `papers.csv` and more, plus `database.xlsx`. No cell
is left empty: the `basis` column says whether each answer was stated, inferred or assumed.

**2 · WebScraping.** Two methods that build one database — both save PDFs in `WebScraping/papers/`
and extract into `WebScraping/web_output/` (the same files as part 1). See [the two web methods](#the-two-web-methods).
- *Method 1 — search open sources* (`python -m WebScraping`): searches 14 services (OpenAlex, arXiv,
  Crossref, Semantic Scholar, …) with the queries of `configs/sse.yaml`, keeps the papers whose title
  and abstract match, downloads the legal copies and extracts them. Your e-mail and the API keys (all
  free, all optional) are set with the **API keys…** button of the web windows — one card per
  organization, each with a link to get a free key — and saved in `WebScraping/averageScrap/.env`;
  `python -m WebScraping --check` tests them.
- *Method 2 — moukhlij4scraping*: collect the DOIs of the topic, fetch a PDF for each, extract.

**3 · SelectingTopMaterial.** Takes one activation energy per material and sorts the materials into
**Superionic** (< 0.25 eV), **Performant** (< 0.30), **Acceptable** (< 0.40) or Rejected. Writes
`SelectingTopMaterial/results/` (`top_materials.csv`, `selection.xlsx`, `report.html`, …). The
limits are in `criteria.toml`; filters such as `--element Na` or `--origin experimental` narrow the
ranking.

**4 · Crystal and Structure Classification.** Puts each material in its structure family (oxide,
sulfide, halide, …) and, when it has one, its crystal family (NASICON, garnet, argyrodite, …). It
writes one database per class into `crystal_structure/` and `structure_families/`, each split into
`bulk/`, `grain_boundary/` and `total/`, plus `all_materials.csv`. Part 3 can rank one class:
`python -m SelectingTopMaterial --source Classification/crystal_structure/garnet`.

## The two web methods

Both live inside `WebScraping/` and feed the one database (`WebScraping/papers/` → `WebScraping/web_output/`).
Open them together from `make gui` → **2 · Web scraping**, or on their own with `python -m WebScraping gui`.

**Method 1 — search open sources** (`WebScraping/averageScrap/`). The default: `python -m WebScraping`.
See the [WebScraping README](WebScraping/README.md).

**Method 2 — moukhlij4scraping.** Three steps:

```bash
# 1. collect the DOIs of the topic (OpenAlex, Crossref, Semantic Scholar, arXiv, Google Scholar)
python WebScraping/Fetch_DOIs/get_dois.py --count 500     # adds 500 new DOIs → dois.csv + dois.txt (no --count: until Ctrl-C)
# 2. fetch a PDF for each DOI into WebScraping/papers/
pip install -r WebScraping/moukhlij4scraping/requirements.txt   # once; needs Google Chrome
python WebScraping/moukhlij4scraping/run.py --from-fetch -l WebScraping/papers   # reads Fetch_DOIs' dois.txt
# 3. extract (the part-1 pipeline, into WebScraping/web_output/)
python -m WebScraping --stage extract
```

Step 1 writes two files: `dois.csv` (title, year, authors, …) and `dois.txt` (just the DOIs, one per
line) — the second is the input step 2 reads. `--from-fetch` is short for
`-i WebScraping/Fetch_DOIs/dois.txt --txt`.

Step 1 always **adds** to the list. `--count N` (1 or more) adds N new DOIs; without it there is no limit
until you stop it — and the window always asks how many first. When the job's keywords stop finding new
DOIs, it goes on with keywords made of the job's topic and property words, so the count can be reached.
Details: [WebScraping README](WebScraping/README.md).

The GUI runs these three as buttons. Method 2 does not only fetch open-access copies, so check your
institution's rules; it is used here for academic literature research.

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

## Cite

If you use MoukhlijMatExtract in your research, please cite it — see [`CITATION.cff`](CITATION.cff)
(GitHub shows a "Cite this repository" button). Add your ORCID and a release DOI there when you have them.

## License

MoukhlijMatExtract is released under the [MIT License](LICENSE) © 2026 Younes Moukhlij.
