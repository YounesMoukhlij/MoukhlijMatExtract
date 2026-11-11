# MoukhlijMatExtract — manual

How to install MoukhlijMatExtract (MME), use every part of it for solid electrolytes, cathodes and anodes, read
its outputs, measure its accuracy and reproduce a result. Written for users and for reviewers of work that
uses it.

- **Every option of every command:** [COMMANDS.md](COMMANDS.md). It is generated from the commands themselves, so
  it is always complete.
- **Every column of every table:** [DATA_DICTIONARY.md](DATA_DICTIONARY.md).
- **What the program does not do well, with the measurements:** [LIMITATIONS.md](LIMITATIONS.md).

---

## Contents

1. [What MME does](#1--what-mme-does)
2. [Install and check the installation](#2--install-and-check-the-installation)
3. [Three ways to run a command](#3--three-ways-to-run-a-command)
4. [Where everything is saved](#4--where-everything-is-saved)
5. [Electrolytes, cathodes and anodes](#5--electrolytes-cathodes-and-anodes)
6. [Step by step](#6--step-by-step)
7. [Reading the outputs](#7--reading-the-outputs)
8. [Measuring the accuracy](#8--measuring-the-accuracy)
9. [Reproducing a result](#9--reproducing-a-result)
10. [Where the papers come from](#10--where-the-papers-come-from)
11. [Every command at a glance](#11--every-command-at-a-glance)
12. [Troubleshooting](#12--troubleshooting)

---

## 1 · What MME does

MME reads scientific papers (PDF) about battery materials and builds a database of their ion-transport data.
It covers three domains, each with its own search and its own database:

| Domain | Materials |
|---|---|
| Electrolytes | solid-state electrolytes: oxides, sulfides, halides, hydrides … |
| Cathodes | layered oxides, spinels, olivines and other polyanions, Prussian blues … |
| Anodes | graphite and hard carbon, Si/Sn/Sb alloys, titanates and niobates, conversion oxides, metal anodes |

**The data extracted:**
- **Values:** activation energies, ionic and electronic conductivities and diffusion coefficients, converted to
  common units. The electrode jobs also extract capacity, capacity retention, voltage and rate capability.
- **What each value is for:** the material, temperature, pressure, transport component (bulk, grain boundary,
  total, surface), measured or computed, the paper's own result or a cited one, the mobile ion, and, for
  activation energies, the kind of energy.
- **Where each value comes from:** paper, page, section, sentence, and the table or figure. A `basis` column says,
  for every answer, whether it was stated or assumed, and why.

**The parts:**

| Part | Command | Input | Output |
|---|---|---|---|
| 1 · Local extraction | `mme-local` | your PDFs | a database |
| 2 · Web scraping | `mme-dois`, `mme-web` | keywords and DOIs | legal open-access PDFs, then a database |
| 3 · Ranking | `mme-rank` | one or more databases | materials ranked by activation energy, with an HTML report |
| 4 · Classification | `mme-classify` | one or more databases | materials sorted by crystal-structure type and structure family |
| Evaluation | `mme-eval` | a database and a person's checks | precision, recall, F1 with intervals; recall against curated databases |
| Release | `mme-release` | the databases and results | one licence-checked folder and `.zip` with datasheet and checksums |

**The window:** `mme-gui` opens one window with a button per part. Everything in this manual can also be done
from the terminal.

---

## 2 · Install and check the installation

**Requirements:**
- Python 3.11 or newer.
- Tesseract OCR, for scanned PDFs: `brew install tesseract`, `sudo apt install tesseract-ocr`, or the Windows
  installer.
- Tk, for the windows only: included with python.org Python; `brew install python-tk@3.13`;
  `sudo apt install python3-tk`.

**From PyPI:**

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install moukhlijmatextract
python -m spacy download en_core_web_sm                 # the English language model, once
```

**From the source code** (gives the `make` shortcuts and the tests):

```bash
git clone https://github.com/YounesMoukhlij/MoukhlijMatExtract.git && cd MoukhlijMatExtract
make install            # .venv/, requirements.txt, the project, the language model
make install-locked     # instead: the exact versions of requirements.lock, to reproduce published results
```

**Check the installation:**

```bash
mme --version           # MoukhlijMatExtract <version> (mme)
mme help                # every command at a glance
make test               # source code only: the whole test suite (about 3 minutes)
make demo               # two open-access example papers through every part -> examples/output/
```

`make demo` should end with a database, a ranking and a classification in `examples/output/`. Its values are
listed in `examples/expected_values.csv`.

---

## 3 · Three ways to run a command

Every command runs in three equivalent ways. Use the one that suits you:

| Installed command | One command for all | From the source folder |
|---|---|---|
| `mme-local --input pdfs` | `mme local --input pdfs` | `make local INPUT=pdfs` |
| `mme-web --job configs/cathode.yaml` | `mme web run --job configs/cathode.yaml` | `make web JOB=configs/cathode.yaml` |
| `mme-rank --domain anode --kind arrhenius` | `mme rank --domain anode --kind arrhenius` | `make rank DOMAIN=anode KIND=arrhenius` |

**With `make`:**
- An option is written `NAME=value`, named after the option: `--min-confidence 0.5` is `MIN_CONFIDENCE=0.5`.
- A switch is on with `NAME=1`.
- `make help` lists every target and every option. `make <part>-help` prints a command's own help.

**Finding the options:** add `--help` to any command for its options. `mme commands` prints every option of every
command, and [COMMANDS.md](COMMANDS.md) holds the same.

---

## 4 · Where everything is saved

Every command works in one folder, `~/MoukhlijMatExtract/`. Relative folders given to a command are read from
there.

```
~/MoukhlijMatExtract/
├── configs/
│   ├── sse.yaml                 electrolyte search (job file)
│   ├── cathode.yaml             cathode search
│   └── anode.yaml               anode search          (made on the first run when missing)
├── LocalExtraction/
│   ├── papers/                  your own PDFs (electrolytes); papers_cathode/, papers_anode/ for electrodes
│   └── local_output/            database of your PDFs;  output_cathode/, output_anode/
├── WebScraping/
│   ├── papers/                  downloaded PDFs + search ledger (electrolytes); papers_cathode/, papers_anode/
│   ├── web_output/              database of the downloaded papers; web_output_cathode/, web_output_anode/
│   └── Fetch_DOIs/              DOI lists (dois.csv, dois_cathode.csv, dois_anode.csv)
├── SelectingTopMaterial/results/   the ranking;  results_cathode/, results_anode/
├── Classification/              crystal_structure/, structure_families/
├── Evaluation/                  annotation workbooks, scores, curated-database comparison
└── Release/                     the dataset folders and .zip
```

**What the program never does:**
- delete or change your PDFs;
- extract a paper twice;
- overwrite a database it cannot read.

A rebuild (`--rebuild`) first moves the present database to `<output>/previous_<date>/`.

---

## 5 · Electrolytes, cathodes and anodes

**The domain setting:**
- **Where it is set:** in the job file (`extract.domain`) for the web, or with `--domain` for your own PDFs.
- **What it does:** it says what a database is about. It decides which values are flagged as being of a material
  of another kind: their `plausibility` reads `check: …` and the ranking leaves them out.
- **Rule:** keep one database folder per domain.

| Domain | Kept | Flagged |
|---|---|---|
| `electrolyte` | candidate solid electrolytes | electrode materials (transition-metal oxides and phosphates, layered, spinel, olivine), alloys, lithiated carbon, interphase compounds and simple salts (LiF, Li2CO3 …), molecules, composites with a polymer, gel or framework |
| `cathode` | cathode materials | solid electrolytes, interphase compounds and simple salts, alloys, lithiated carbon, molecules |
| `anode` | alloys, carbons, titanates, niobates, conversion oxides | solid electrolytes, interphase compounds and simple salts, molecules |

**In every domain**, a doped sample stored under its parent formula is flagged ("the Al-doped LLZO" saved as
Li7La3Zr2O12), as is an energy that is not of ion migration (see `energy_kind` in § 7).

**One run of each domain:**

```bash
# Electrolytes
mme-web run --job configs/sse.yaml
mme-rank --domain electrolyte --kind arrhenius --origin experimental --attribution this-work

# Cathodes
mme-web run --job configs/cathode.yaml --output WebScraping/web_output_cathode
mme-rank --domain cathode --source WebScraping/web_output_cathode --kind arrhenius

# Anodes
mme-web run --job configs/anode.yaml --output WebScraping/web_output_anode
mme-rank --domain anode --source WebScraping/web_output_anode --kind arrhenius
```

With make: `make web-cathode`, `make rank-cathode`, `make web-anode`, `make rank-anode`,
`make local-cathode`, `make local-anode`.

**The ranking classes:**
- **Electrolytes** (`criteria.toml`): Superionic < 0.25 eV, Performant < 0.30 eV, Acceptable < 0.40 eV, else
  Rejected.
- **Electrodes** (`criteria_cathode.toml`, `criteria_anode.toml`): Low barrier < 0.30 eV, Moderate barrier
  < 0.50 eV, else High barrier.

The electrode limits are starting points, not literature criteria. A study that uses them should set and justify
its own: copy the file and pass it with `--criteria my_criteria.toml`.

---

## 6 · Step by step

### 6.1 · Your own PDFs — `mme-local`

```bash
mme-local                                          # the PDFs of LocalExtraction/papers -> local_output/
mme-local --input ~/pdfs --output LocalExtraction/my_output
mme-local --domain cathode --input ~/pdfs/cathodes --output LocalExtraction/output_cathode
mme-local --offline                                # do not complete titles, DOIs and licences from OpenAlex
mme-local --rebuild                                # extract every PDF again
mme-local gui                                      # the same, in a window
```

Paywalled papers your institution gives you access to are read this way. They are released as your own copies
(§ 10).

### 6.2 · Papers from the web — `mme-dois` and `mme-web`

The job file (`configs/*.yaml`) holds:
- the search queries and years;
- the sources searched;
- the words that decide which papers are on topic: `topic_words`, `property_words`, `exclude_words` and
  `min_score`;
- the download folder;
- what is extracted, and the domain.

Edit it in a text editor, or with **Search settings…** in the window.

```bash
mme-dois --count 500                    # 1 · Fetch DOIs: up to 500 new DOIs for the job's keywords
mme-web run                             # 2 · Search (keywords + DOIs) and score each paper, then 3 · download and 4 · extract
mme-web run --stage fetch --limit 50    # 3 · download up to 50 approved papers (legal copies only), then extract
mme-web run --stage extract             # 4 · only extract what is downloaded
mme-web run --check                     # test the network, the API keys and the folders first
mme-web run --yes                       # approve every paper found without a review
mme-web gui                             # the same steps as buttons, the review in a table
```

**How a paper is kept:**
- **Screening:** it is kept when its title and abstract score at least `min_score` on the job's words, and name a
  topic word.
- **Review:** with `screen.review: true` in the job file, the run stops after screening so you can check
  `WebScraping/papers/candidates.csv` (its `decision` column) before anything is downloaded. Then run
  `--stage fetch`. The shipped jobs say `false`: papers that pass the screening are downloaded.
- **Records:** every decision is recorded with its reason in the search ledger (`WebScraping/papers/ledger.sqlite`
  and `candidates.csv`).

### 6.3 · Ranking — `mme-rank`

```bash
mme-rank                                              # every database found, every component apart
mme-rank --kind arrhenius                             # one kind of energy only (§ 7)
mme-rank --origin experimental --attribution this-work   # measured values, from the papers' own work
mme-rank --component bulk --element Na --top 20
mme-rank --domain cathode --source WebScraping/web_output_cathode
mme-rank --policy optimistic                          # a material's lowest value instead of its median
mme-rank --include-flagged                            # also rank the values flagged check: …
mme-rank --open                                       # and open the HTML report
```

**How a material is ranked:**
- **Components:** bulk, grain boundary and total are ranked apart, never mixed.
- **Its value:** by default the confidence-weighted median of its values.
- **Its class:** read from the criteria file.
- **The report:** shows every value behind each material, with its sentence and page.

**For a publication:**
- Rank one kind of energy, one origin and one mobile ion at a time.
- Report the number of independent papers behind each material.

### 6.4 · Classification — `mme-classify`

```bash
mme-classify                            # every database -> Classification/crystal_structure/, structure_families/
mme-classify --source WebScraping/web_output_cathode --out Classification_cathode
```

It writes one database per class, which `mme-rank --source` can rank on its own.

### 6.5 · The dataset — `mme-release`

```bash
mme-release                             # databases + ranking + classification -> Release/<name>/ and .zip
mme-release --finish Release/<name>     # after completing its README: SHA256SUMS and .zip again
```

**What it contains:**
- every value and bibliographic field;
- the text of a paper (sentences, captions, tables), only where its licence lets anyone share it;
- the data dictionary, the run manifests and `requirements.lock`;
- a datasheet;
- `SHA256SUMS`.

Papers with no record of a legal copy are left out and listed in `excluded.csv` (§ 10).

---

## 7 · Reading the outputs

Each database folder holds linked tables, as CSV files, one workbook (`database.xlsx`) and `database.json`:

| Table | One row per |
|---|---|
| `papers.csv` | paper: bibliographic data, licence, where the copy came from, file SHA-256, code version |
| `activation_energy.csv`, `ionic_conductivity.csv`, `electronic_conductivity.csv`, `diffusion_coefficient.csv` | value of that quantity, in eV, S/cm, S/cm, cm²/s |
| `properties.csv` | every property value (capacity, voltage, band gap …) |
| `materials.csv` | material mention |
| `relations.csv`, `tables.csv`, `figures.csv`, `equations.csv`, `workflow.csv`, `methods.csv`, `summary.csv` | link, table, figure, equation, step, setting, paper |

**The columns that matter most when using the data** (every column: [DATA_DICTIONARY.md](DATA_DICTIONARY.md)):

| Column | Meaning |
|---|---|
| `plausibility` | `in range`, or `check: <why>` (out of range; electrons; a material of another domain; a doped sample stored as its parent; an energy that is not of ion migration). The ranking leaves out `check:` values unless `--include-flagged` |
| `needs_check` | `no`, or `yes: <reasons>`: the values most worth a person's look (unusual formula, material from another sentence, table text, low confidence …) |
| `energy_kind` | activation energies only. `arrhenius` (long-range: impedance, molecular dynamics, PFG-NMR), `migration_barrier` (static barrier of one hop: NEB), `bvse`, `local_hop` (NMR relaxation, QENS), `vtf`, `rotation`, `charge_transfer`, `electron_transfer`, `reaction`, `unspecified`. Different kinds are different quantities |
| `data_origin`, `attribution`, `transport_component`, `mobile_ion`, `temperature` | measured or computed, own or cited, bulk / grain boundary / total / surface, the moving ion, the temperature (range) |
| `basis` | for each answer above: `stated (…)` with the words, `paper (…)`, `assumed (…)` with the reason. `n_assumed` counts the assumed ones |
| `material_link` | how the value was tied to its material. `paragraph_topic` and `previous_sentence` (taken from the context) are the least reliable |
| `sentence`, `page`, `section`, `source` | where to check the value in the paper |

---

## 8 · Measuring the accuracy

Extracted values must be checked before they support a conclusion. The measured precision is in
[LIMITATIONS.md § 2](LIMITATIONS.md). The tools to measure it again:

```bash
mme-eval sheet --papers 60              # papers drawn at random -> Evaluation/annotation.xlsx (a Guide sheet inside)
#   a person marks each value correct / partly / wrong, and adds the values missed
mme-eval score                          # precision, recall, F1 with 95 % intervals -> Evaluation/scores/report.md
mme-eval agree a.xlsx b.xlsx            # two annotators: Cohen's kappa and F1 between them
mme-eval reference                      # recall against the curated OBELiX and Liverpool databases
mme-eval score --predictions other.csv  # another tool scored on the same papers, side by side
```

**How it is done:**
- **Sampling:** papers are drawn with a fixed seed (`--seed`), so the same draw can be repeated.
- **Intervals:** they resample whole papers.
- **Default draw:** only papers that `mme-release` would publish are drawn, unless `--all-papers`.

**For a publication:**
- Annotate the papers the results rest on, with two people on part of them.
- Report the κ, and deposit the workbooks with the dataset.

---

## 9 · Reproducing a result

Everything needed to reproduce a database, a ranking or a release is recorded:

| What | Where |
|---|---|
| The code | the git commit of every run, in `run_manifest.json` (`environment.git`), with a flag when the working tree had uncommitted changes |
| The environment | `requirements.lock` (`make install-locked`); Python, platform, package versions, Tesseract and the language model in each run manifest |
| The settings | each run's command and settings (input, output, properties, domain …) in `run_manifest.json`; the job file for the web |
| The papers | `papers.csv`: DOI, source, licence, retrieval date, SHA-256 of each PDF, and the code version that read it (`extracted_with`) |
| The files | each run manifest lists the rows and SHA-256 of every file it wrote; a release carries `SHA256SUMS` |
| The random draws | `--seed` of `mme-eval sheet` and of the bootstrap |

**To reproduce a published database:**

```bash
git checkout <the commit or tag of the release>
make install-locked
mme-local --input <the released PDFs> --output LocalExtraction/reproduced --offline --domain <its domain>
# compare activation_energy.csv etc. with the released ones (same values; rows may be in another order)
mme-rank --source LocalExtraction/reproduced --domain <its domain> <the filters of the publication>
```

**Notes:**
- **Order and bytes:** the content is reproducible, but the row order depends on the number of workers. Compare
  tables sorted, or run with `--workers 1`.
- **Metadata:** completing titles and licences from OpenAlex (`--offline` turns it off) can differ between dates.
- **Downloads:** they cannot be repeated exactly, because open-access copies come and go. Deposit the search
  ledger (`candidates.csv`, with every decision and its reason) and the job file with the dataset. `mme-release`
  carries the list of papers, not the ledger.

---

## 10 · Where the papers come from

**What is downloaded:**
- `mme-web` downloads only legal open copies: open-access publishers, repositories, preprint servers, and
  publisher APIs for which you hold a key.
- Each PDF is saved with a sidecar file recording its source, URL, licence and retrieval date. robots.txt and rate
  limits are respected.

**What is released:**
- `mme-release` publishes a web paper only when the record of its legal source is kept with it, and your own PDFs
  as yours.
- A paper with no such record, or recorded as coming from a shadow library, is left out of the databases, the
  ranking and the classification, and listed in `excluded.csv`.

---

## 11 · Every command at a glance

| Command | What it does | make |
|---|---|---|
| `mme` | every command in one: `mme help`, `mme commands`, `mme <part> …` | `make help`, `make manual`, `make commands` |
| `mme-gui` | the main window | `make gui` |
| `mme-local` | read your PDFs into a database | `make local`, `local-gui`, `local-rebuild`, `local-cathode`, `local-anode` |
| `mme-dois` | collect the DOIs of the job's keywords | `make doi` |
| `mme-web` | search, review, download, extract | `make web`, `web-check`, `web-fetch`, `web-extract`, `web-dois`, `web-gui`, `web-cathode`, `web-anode` |
| `mme-rank` | rank by activation energy | `make rank`, `rank-gui`, `rank-cathode`, `rank-anode` |
| `mme-classify` | sort by crystal-structure type and family | `make classify`, `classify-gui` |
| `mme-eval` | `sheet`, `score`, `agree`, `reference` | `make eval-sheet`, `eval-score`, `eval-agree`, `eval-reference` |
| `mme-release` | the dataset, ready to deposit | `make release` |
| (source folder) | install, tests, docs | `make install`, `install-locked`, `lock`, `test`, `demo`, `dictionary`, `commands`, `clean`, `version` |

Every option of each: [COMMANDS.md](COMMANDS.md).

---

## 12 · Troubleshooting

| Problem | What to do |
|---|---|
| `command not found: mme-…` | enter the virtual environment: `source .venv/bin/activate` |
| No language model | `python -m spacy download en_core_web_sm` |
| Scanned PDFs give nothing | install Tesseract (§ 2) |
| A window does not open | install Tk (§ 2); every part also runs in the terminal |
| The web search finds few papers | `mme-web run --check`; add API keys where you have them (see `WebScraping/averageScrap/README.md`) |
| "The database … was written by an earlier version" | answer the question it asks: bring it up to date, or `--rebuild` |
| A value looks wrong | its `sentence` and `page` show where it was read; `basis` shows what was assumed |
| Stop a long run | Ctrl-C or the window's Stop: what is done is kept, and the next run goes on from there |
