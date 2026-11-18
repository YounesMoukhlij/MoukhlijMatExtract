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

**The windows** (`mme-gui`, or the `gui` of any command) fit the screen they open on.
- **Size:** each window opens centred, larger on a large screen, never larger than what the menu bar and the dock
  or taskbar leave. A dialog opens over the window it belongs to.
- **Resizing areas:** wherever two areas share a window, the line between them can be dragged:
  - the controls and the tabs;
  - the tabs and the Activity strip;
  - the ranking's two columns of settings, and its settings and its tables;
  - the Verify tab's list and page, and its details and page;
  - Classification's classes and materials.
- **Dragged lines:** a line you dragged stays where you put it; otherwise it follows the window as it is resized.
- **Small screens:** when the controls do not all fit (a small laptop, or after a line was dragged up), they scroll
  with the mouse wheel or their bar. Nothing is cut off.

---

## 4 · Where everything is saved

Every command works in one folder, `~/MoukhlijMatExtract/`. Relative folders given to a command are read from
there. A job file or a DOI list named on the command line that is not there, but is in the folder the command was
started from (`--job configs/my_job.yaml` in a copy of the source code), is read from that folder instead.

A job's DOIs go to its own list (`search.doi_list` in the job file): `mme-dois --job configs/cathode.yaml` fills
`dois_cathode.csv`, never another job's list. `--out` chooses another file.

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

**One job per family of solid electrolytes.** `~/MoukhlijMatExtract/configs/` holds one job file per family, made
there when missing:
- **structure types:** `garnet`, `nasicon`, `lisicon`, `lgps`, `argyrodite`, `perovskite`, `antiperovskite`,
  `beta_alumina`, `oxide_structure` (spinel, pyrochlore, scheelite, brownmillerite, …);
- **chemical families:** `halide`, `complex_hydride`, `nitride`, `fluoride`, `mixed_anion`, `oxide_chemistry`
  (niobates, tantalates, zirconates, borates, silicates, …);
- **composition systems and material classes:** `sulfide_glass`, `lipon`, `polymer`, `hybrid` (composites, MOF, COF,
  plastic crystals);
- **by mobile ion:** `multivalent` (Mg²⁺, Ca²⁺, Zn²⁺, Al³⁺, Sc³⁺);
- `garnet_nasicon.yaml`, the two families of the screening article together.

[FAMILIES.md](FAMILIES.md) gives each family's kind, prototype and space groups, mobile ions and examples.

Each has the family's queries, topic words and exclusions, and its own DOI list, PDF folder and database. Choose
one as the job file of the Web scraping window, or run `mme-web run --job configs/halide.yaml`.

**Each job its own database.** Without `--output`, `mme-web` (and the Web scraping window) extracts a job's papers
into the folder beside its PDF folder: `WebScraping/web_output` for `WebScraping/papers`,
`WebScraping/web_output_NAME` for `WebScraping/papers_NAME`. So `--output` above only says what is done anyway, and
`configs/garnet_nasicon.yaml` goes into `WebScraping/web_output_garnet_nasicon`. In the window, the results folder
follows the job chosen, unless you chose a folder by hand. The ranking and classification windows offer these
databases without ticking them. The ranking window has the same filters as `mme-rank`, among them “Kind of Ea”
(`--kind`) and “Classes of” (`--domain`).

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
mme-web run --snowball                  # also follow the citations of the papers kept (search.snowball)
mme-web run --update                    # only the papers published since this job's last search
mme-web update                          # the same for every job run before, one after the other
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

**Learning from your decisions:**
- **What it learns from:** once you have decided 10 papers by hand, at least 3 yes and 3 no, a small model of
  your judgement is trained on them. A decision by hand is a yes or no given in the window, or one you changed
  from the proposal in `candidates.csv`.
- **What it does:** it reads the words of each title and abstract, and gives every paper still waiting its chance
  of a yes. This is the `model` column of the window and `model_yes` in `candidates.csv`. The review list then
  puts the most uncertain papers first: deciding those teaches the model most.
- **How good it is:** its accuracy on your own decisions (5-fold cross-validation) is written in the log each time
  it is trained.
- **What it never does:** decide. The job's words still propose, and you decide.

**Keeping a database current** (`mme-web update`):
- **What it does:** every job that has been run is searched again, only for the papers published since its last
  search. New papers are screened, downloaded and extracted into the job's own database as usual.
- **Years, not days:** the sources take years, so the search starts at the year of the last search. A paper
  already in the ledger is not taken twice.
- **Left alone:** jobs never run.
- **Once a month:** schedule it. On macOS or Linux, `crontab -e` and the line
  `0 6 1 * * cd ~ && mme-web update >> ~/MoukhlijMatExtract/update.log 2>&1` (6 a.m. on the 1st). On Windows, a
  Task Scheduler task running `mme-web update`.

**Citation snowballing** (`search.snowball: true`, `--snowball`, or "Follow the citations of the papers kept" in
Search settings…). Keyword searches miss papers that use other words. Snowballing finds them the way a systematic
review does:
- **Seeds:** every paper kept so far (decision `yes`) that has an OpenAlex record.
- **Backward:** OpenAlex gives the papers each seed cites.
- **Forward:** OpenAlex gives the papers citing each seed, the most cited first, up to `search.snowball_citing`
  (100 by default).
- **Screening:** both sets are kept to the job's years and kinds of work. What is new is screened with the job's
  words like any other paper.
- **Records:** each such paper says how it was found in `found_by` (`snowball: cites W…` or
  `snowball: cited by W…`).
- **Repeats:** a seed is not asked again for 30 days, unless `--refresh`.
- **Rounds:** run the search again to snowball from the papers the last round kept.

### 6.3 · Ranking — `mme-rank`

```bash
mme-rank                                              # every database found, every component apart
mme-rank --kind arrhenius                             # one kind of energy only (§ 7)
mme-rank --origin experimental --attribution this-work   # measured values, from the papers' own work
mme-rank --component bulk --element Na --top 20
mme-rank --domain cathode --source WebScraping/web_output_cathode
mme-rank --policy optimistic                          # a material's lowest value instead of its median
mme-rank --include-flagged                            # also rank the values flagged check: …
mme-rank --verified-only                              # only the values checked by hand (the Verify tab)
mme-rank --bootstrap 5000                             # more resamplings for the rank intervals (0: none)
mme-rank --open                                       # and open the HTML report
```

**How a material is ranked:**
- **Components:** bulk, grain boundary and total are ranked apart, never mixed.
- **Its value:** by default the confidence-weighted median of its values.
- **Its class:** read from the criteria file.
- **The report:** shows every value behind each material, with its sentence and page.

**How sure each rank is** (columns `rank_95`, `p_top10`, `evidence` of every table, and the report):
- **Rank interval:** the values of every material are resampled 1,000 times (fixed seed) and the materials
  ranked again each time. `rank_95` is the 95 % interval of a material's rank, and `p_top10` the share of
  resamplings that put it in the top 10.
- **Evidence tier:** A = 3 values or more from 2 papers or more; B = 2 values or more; C = a single value. A
  tier-C material has no spread of its own: its interval only shows how the others move. Read the two together.

**The Arrhenius cross-check.** When a paper gives a material's conductivity at two temperatures or more, they
yield an activation energy of their own. Both conventions are fitted: ln(σT) and ln σ against 1/T. A reported
value that neither fit matches within 0.05 eV (or 20 %) is flagged: the check "Arrhenius fit disagrees" beside
the material, and `arrhenius_check` beside each value. Cited values and room temperature alone are not checked.
`python -m LocalExtraction.arrhenius <database>` lists the disagreements. It flags a value to look at; it never
removes one.

**Checking the values by hand — the Verify tab** (windows 1 and 2):
- **What it shows:** every activation energy with its sentence, beside the page of the PDF it was read from
  (the sentence marked on it).
- **The order:** the values most worth checking first — those the Arrhenius cross-check disputes, those the
  extraction flagged, then the lowest energies (those that would lead a ranking).
- **Your verdict:** **✓ Correct** (c), **✗ Wrong** (w), or **✎ Correct it…** (e) to put right the material,
  number, kind, component, origin or attribution. **↺ Undo** (u) takes a verdict back.
- **Where it is kept:** `~/MoukhlijMatExtract/Verification/<database>.csv`, outside the database. Rebuilding or
  deleting a database never loses it. A value is known by its paper, page, sentence, number and material.
- **In the ranking:** a value marked wrong takes no part; a corrected one takes part as corrected; "Verified
  values only" (`--verified-only`) ranks the checked values alone. Each table says how many of a material's
  values were checked (`verified`).

**For a publication:**
- Rank one kind of energy, one origin and one mobile ion at a time.
- Check by hand at least the values behind the materials you report, and rank with `--verified-only`.
- Report the number of independent papers behind each material, its rank interval and its evidence tier.

**Computed data beside the ranking** (`mme-rank --materials-project`, with a free `MP_API_KEY`). In the Ranking
window:
- **The key:** type your own key in **Materials Project key** (hidden as you type; tick **Show** to read it back)
  and press **Save the key**. It is kept with your other keys, in `~/MoukhlijMatExtract/.env`, which is never
  shared.
- **No key yet:** click "get one (free)" to open the page where a key is had.
- **The entries:** tick **and write each material's entry** before **Rank**.

- **What it writes:** `materials_project.csv` beside the ranking, with each ranked material's Materials Project
  entry: its stability (energy above the convex hull), band gap, space group and a link to its page.
- **Matching:** by reduced formula (Li12P2S10Cl2 is Li6PS5Cl), keeping the most stable entry.
- **No entry:** doped and non-stoichiometric compositions seldom have one, and their row says so.
- **The ranking itself:** unchanged.
- **ICSD:** needs a paid licence, so it is not asked.

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

**Your database against the curated ones** (`mme-eval reference --against WebScraping/web_output_garnet`):
- **What is compared:** each room-temperature material of OBELiX and of the Liverpool dataset is looked for in
  your results folder, from any paper (Li6PS5Cl and Li12P2S10Cl2 are the same material). Where both have it, the
  median of your room-temperature conductivities is set against the median of theirs.
- **What it gives:** how many of their materials your database holds, the share of those whose values agree
  within 0.1, 0.5 and 1 decade, and every material in `Evaluation/reference/against_<folder>.csv`.
- **What it does not give:** precision, since a curated database is not exhaustive.
- **Values compared:** these databases record conductivities, not activation energies.

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

**How much was reached** (`mme-web coverage`, or **Coverage…** in the Web scraping window):
- **By job:** for each job file, the papers found, screened, proposed, downloaded (with the share of those
  proposed), left without a legal copy, and extracted, with the activation energies its database holds.
- **By publisher:** the same counts, every job together. A publisher whose proposed papers were seldom downloaded
  is under-represented in the corpus, which is worth stating in an article's limitations.
- **Where:** `WebScraping/coverage/`: `coverage.md` (both tables, ready to quote), `coverage_by_family.csv` and
  `coverage_by_publisher.csv`.
- **Safety:** the ledgers are read, never changed.

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
| The program stopped with an error | the full report is in `~/MoukhlijMatExtract/logs/crash_<date>.log` (the message says where); send that file with your report. It holds the version, the command, the Python and system, and the traceback, never a key |

### Environment variables

Settings the commands read from the environment (none is needed for normal use):

| Variable | Effect |
|---|---|
| `MME_EMAIL` | the contact e-mail sent to the open indexes (Unpaywall needs one); set in **API keys…**, saved in `~/MoukhlijMatExtract/.env` |
| `MME_OFFLINE` | `1`: no network lookup of a paper's title, authors, journal and license (what `--offline` does) |
| `MME_NO_NET_WAIT` | `1`: a web request does not wait for the internet to come back; it fails at once |
| `TESSERACT_CMD` | the full path of the Tesseract program, when it is not found on the `PATH` |
| `MME_AS_COMMAND` | `1`: the help shows the `mme-*` command names (used to write `docs/COMMANDS.md`) |
