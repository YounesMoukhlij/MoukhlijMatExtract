# LocalExtraction — Part 1

A part of [MoukhlijMatExtract (MME)](../README.md) · Author: Younes Moukhlij

Turns a folder of battery/materials-science PDFs into a structured database: it parses each paper
(text, tables, figures, equations, OCR for scanned pages), finds the materials and their
properties, ties each value to its material and conditions, and exports linked CSV files, an Excel
workbook and JSON. The web project ([WebScraping](../WebScraping/README.md)) runs this same
pipeline on the PDFs it fetches.

| | |
|---|---|
| **Input** | the PDFs at the top level of `LocalExtraction/papers/` |
| **Output** | the database `LocalExtraction/local_output/` — see [Output](#output) |
| **Read by** | [SelectingTopMaterial](../SelectingTopMaterial/README.md) and [Crystal and Structure Classification](../Classification/README.md) |

## Set up (once)

The whole project works inside one virtual environment (venv), `.venv/` in the project folder.
From the project folder (the one that holds `LocalExtraction/`), with Python 3.11 or newer:

```bash
python3 -m venv .venv                     # create the venv, once
source .venv/bin/activate                 # enter it (Windows: .venv\Scripts\activate)
pip install -r requirements.txt           # install the packages inside it
python -m spacy download en_core_web_sm   # and the language model
```

Then work inside it: enter it (`source .venv/bin/activate`) in every new terminal before you run
the commands below; your prompt then starts with `(.venv)`. The
[main README](../README.md#install-once) has the whole setup, Tesseract included.

## Run it

From the project folder, inside the venv:

```bash
python -m LocalExtraction                                   # LocalExtraction/papers → LocalExtraction/local_output
python -m LocalExtraction --input /path/to/pdfs --output /path/to/database --workers 4
python -m LocalExtraction --rebuild                         # read every PDF again (old files kept aside)
python -m LocalExtraction --offline                         # do not complete the papers' metadata from OpenAlex
python -m LocalExtraction gui                               # the window
```

| Flag | Short | Default | Description |
|---|---|---|---|
| `--input` | `-i` | `LocalExtraction/papers` | Directory containing input PDFs |
| `--output` | `-o` | `LocalExtraction/local_output` | Directory to write the extracted database into |
| `--workers` | `-w` | `4` | Number of PDFs to process in parallel |
| `--verbose` | `-v` | off | Enable debug-level logging |
| `--rebuild` | | off | Extract every PDF again instead of only the new ones; the present database files are moved to `<output>/previous_<date>/`, not deleted, and every paper of it comes back (see [Adding papers](#adding-papers-to-a-database)) |
| `--offline` | | off | Do not ask OpenAlex for the papers' title, authors, journal, DOI, year and license (see [What each paper is](#what-each-paper-is-paperscsv)) |

Re-running the command on the same `--output` directory is safe and incremental: papers already
recorded in its `papers.csv` are skipped, and only new PDFs are processed and **appended** to the
tables — see [Adding papers to a database](#adding-papers-to-a-database). Papers are saved to the
database every 50 papers rather than only at the end, so a crash or a Ctrl-C in a long run loses at
most one batch; the Excel workbook is built once, at the end, from the CSVs.
(Only the top level of `LocalExtraction/papers/` is read: PDFs fetched by the web project live in `WebScraping/papers/`.)
A database written by an earlier version of the program is rebuilt by itself: its files are moved
to `<output>/previous_<date>/` and the PDFs are read again.

## Adding papers to a database

Put the new PDFs in the folder (or point `--input` at another one) and run the same command on the
same `--output`: their rows are added **after** the rows already in every table; nothing already
there is changed or lost.

- **A PDF is known by its name and its content** (its SHA-256, in `papers.csv`). The same file again
  — under its name or as a copy under another — is skipped. **Another file under a name the
  database has** (a new `Article 1.pdf`) is extracted: if it is the same paper (the same DOI or
  title) — a corrected copy — its rows replace that paper's; if it is another paper, it is added
  as a paper of its own, `paper_id` = the name and the start of its checksum
  (`Article 1.pdf#3fa2c1d0`), and the first one stays.
- **No paper is ever in a table twice**: rows written again for a paper replace its earlier ones.
- **A table opened and saved in a spreadsheet** (with `;` between the columns, in Windows-1252) is
  read as it is and written back as this program writes it; a column you added by hand is kept
  (the new rows say `not filled (a column added by hand)` in it).
- **A table that cannot be read stops the run before anything is written**, with a message naming
  it: no file is written over, so no row is lost. Save it again as CSV, or move it out of the
  folder to start that table anew.
- Every file is written whole or not at all (a new file takes the old one's place), and
  `papers.csv` last: a crash never leaves half a table, and a paper counts as done only once all
  its rows are in.
- **A rebuild** (`--rebuild`, **Results → Rebuild…**, or a database of an earlier version) brings
  back every paper of the database it replaces: the PDFs of the folder are extracted again, so are
  those read from elsewhere on this computer (where `papers.csv` says they were), and the papers
  whose PDF is no longer anywhere are carried over from the `previous_<date>` folder as they were —
  a column the new version adds says `not recorded (written by an earlier version of
  MoukhlijMatExtract)` for them. A rebuild that is stopped goes on where it was on the next run.

## The window

`python -m LocalExtraction gui` (it takes `--input`, `--output` and `--workers` too) runs the same
extraction: it reads the PDFs of a folder that its results folder does not hold yet, shows each
paper as it is done, and then its activation energies.

The table shows the activation energies of the results folder — the
material, the value, the part of the paper it was read from (text, table or figure) and the page,
how many of its answers are defaults — and a double click shows the sentence, the `basis` and
every other column. The *Results* menu opens the folder or the Excel workbook; **Results →
Rebuild…** moves the database into a `previous_<date>` folder so that its articles are extracted
again (after an update of the program); nothing is deleted. A database written by an earlier
version is offered the same when an extraction starts. Stop lets the papers in progress finish,
so their work is not lost; everything is resumable.

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
- **A complete row for every value** — no cell of any table is empty: what the paper leaves
  unsaid about a value is answered with the likeliest value, marked `assumed` with its reason and
  counted in `n_assumed`, so that a default is never taken for a statement of the paper; what the
  PDF does not say about the paper itself is completed from OpenAlex.
- **Incremental runs** — re-running the pipeline on the same output folder skips papers that are
  already in `papers.csv` and appends the new PDFs' rows to every table, never losing a row;
  `--rebuild` extracts everything again and keeps every paper.
- **Multiple export formats** — normalized relational CSVs (`papers`, `materials`, `properties`,
  `activation_energy`, `ionic_conductivity`, `electronic_conductivity`, `diffusion_coefficient`,
  `unassigned_values`, `methods`, `relations`, `tables`, `figures`, `equations`, `workflow`,
  `summary`), a multi-sheet Excel workbook and nested JSON.

## How it works

```
LocalExtraction/papers/*.pdf
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
exporter.py      — writes LocalExtraction/local_output/ or WebScraping/web_output/ {database.json, database.xlsx, *.csv}
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

## Output

Each project fills its own folder — `LocalExtraction/local_output/` for the articles of your computer,
`WebScraping/web_output/` for the articles fetched from the web — with the same files:

| File | Contents |
|---|---|
| `papers.csv` | One row per paper: title, authors, journal, DOI, year and where they come from (`metadata_basis`), counts, and its provenance — the source, URL, license, retrieval date, checksum and OpenAlex id (for a PDF of this computer: the file itself, its date and checksum). See [What each paper is](#what-each-paper-is-paperscsv) |
| `materials.csv` | Every material found: its formula as the paper wrote it (`raw_formula`) and in one spelling per composition (`normalized_formula`), `elements` (the composition), `structure` with its `structure_basis`, and `ionic_radii`, each with how it is known |
| `activation_energy.csv` | The activation energies, in one numeric column in eV — whatever the paper called it: see [One activation energy](#one-activation-energy) |
| `ionic_conductivity.csv` | The ionic conductivities, in one numeric column in S/cm (`ionic_conductivity_S_cm`) |
| `electronic_conductivity.csv` | The electronic conductivities, in S/cm (`electronic_conductivity_S_cm`) |
| `diffusion_coefficient.csv` | The diffusion coefficients, in cm²/s (`diffusion_coefficient_cm2_s`) |
| `properties.csv` | **Every value of a material**, of any property (the four above too), with its unit, confidence and full [value context](#value-context) — up to 25 per property and transport type, a guard against a table read wrongly |
| `unassigned_values.csv` | The values no material could be established for (a class of materials, a sample label the paper never defines, a sentence cut by a page break). Same columns as `properties.csv`, without the material ones |
| `methods.csv` | How the study was done and what it mentions: DFT / AIMD / ML settings, synthesis conditions, characterization techniques, structure mentions. These have no material and no measurement context, so they have no such columns |
| `relations.csv` | Every material ↔ value link, with the method that made it |
| `tables.csv` | The tables of the papers (caption, headers, rows, the column of material names). What PDF extraction took for a table but is none — figure text, a reference list, an empty grid — is left out; a table printed without a caption is named from its headers (`caption_basis` says so) |
| `figures.csv` | Figure captions and the materials, properties, tables, equations and methods they name |
| `equations.csv` | The equations, with their type (Arrhenius, Nernst-Einstein, MSD/Diffusion, Einstein relation, NEB, Butler-Volmer, Fick's law, Vegard's law, a chemical reaction, a linear fit or another expression), variables and context sentence. A value written with an "=" (`x = 0`, `Ea = 0.3 eV`) and a substitution note (`M = Dy, Ho, Y`) are not equations and are left out |
| `workflow.csv` | Ordered experimental/computational workflow steps per paper |
| `summary.csv` | One line per paper: its title and year, its materials, how many values of each transport quantity it gave and the lowest activation energy / highest conductivities (`highlights`) |
| `database.xlsx` | All of the above as sheets in one workbook |
| `database.json` | All of the above as nested JSON, one record per paper |

**No cell is left open.** Every table has only columns that apply to each of its rows — the
transport component (bulk, grain boundary, surface, total) is a column of the four tables of the
transport quantities, where it applies to every row — and every cell is answered: from the paper,
from OpenAlex, from the composition, or with the likeliest value marked as assumed, the `basis`
columns saying which. A table with no row (no unassigned value, say) is still written with its
header. See [No open answer](#no-open-answer).

## One activation energy

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

## Value context

`properties.csv`, the tables of the four transport quantities and `unassigned_values.csv` (and the
matching sheets and JSON records) describe each value with the same columns.

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
| `data_origin` | `experimental` or `simulation` (DFT, AIMD/MD, NEB, ML predictions, …) |
| `transport_component` | In the tables of the four transport quantities: `bulk`, `grain_boundary`, `surface` or `total`. "The total and bulk conductivities are 0.4 and 2.5 mS/cm" gives each value its own, in that order |
| `attribution` | `this work` for a result of the paper itself, `cited` for one it quotes from another source ("Kamaya et al. reported …", "… 12 mS/cm [5]", every value of a review) |
| `n_assumed` | How many of the answers (structure, temperature, pressure, origin and — for a transport quantity — component) are defaults rather than read from the paper: sort by it to see the best-documented rows first |
| `basis` | Where each of those answers comes from — see next |

## Where each answer comes from: `basis`

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
| `assumed` | A convention or the likeliest value, with its reason in brackets — see below and [No open answer](#no-open-answer) |

The conventions, all marked `assumed` so that they can be filtered out:

- **Pressure** — `ambient pressure` when the paper states none (not in a paper where pressure is one of the variables).
- **Transport component** — a simulated value is a `bulk` one (not in a paper about grain boundaries, nor when the sentence speaks of a surface or an interface); a measured conductivity or activation energy is the `total` of the pellet, bulk and grain boundaries together, unless the wording says which part it is; an NMR value is a `bulk` one.
- **Temperature** — `0 K` for a static calculation; `room temperature` for a conductivity or diffusion coefficient given without one, in a paper where those that do have a temperature are (at least 3 of them, and 70%) at room temperature.
- **Origin** — a quoted conductivity is a measured one unless its sentence calls it computed.

To keep only what the paper itself states, drop the rows (or ignore the cells) whose `basis` says
`assumed` for the column you use; `n_assumed` counts them per row.

## No open answer

A value with a hole in its row cannot be filtered or compared, so for no value of a material is
anything left open. After every level above has been tried, what is still open is answered with
the likeliest value — and says `assumed`, with the reason:

| Still open | Answered with |
|---|---|
| origin | `simulation` for a value of a computational paper, `experimental` for one of an experimental paper; otherwise by what the value is: a *migration / diffusion / energy barrier* or a *migration energy*, a formation energy, an energy above the hull, a band gap, a Bader charge … is usually computed; an *activation energy*, a conductivity, a lattice parameter, a capacity … usually measured |
| transport component | `bulk` for a computed value (and for an NMR one, a measured diffusion coefficient and the rotation of an anion group), `total` for a measured conductivity or activation energy (and an electronic conductivity, measured by DC polarization on a pellet) |
| temperature | activation energy: `0 K` for a computed barrier (a static calculation, unless its own sentence speaks of dynamics or of a fit); the range the paper gives for its own runs or measurements; else `600-1200 K` for a simulated one, `room temperature` for a measured one. Conductivity: `room temperature` (measured, or computed and extrapolated). Diffusion coefficient: the paper's range, else `600-1200 K` when computed, `room temperature` when measured. Any other property: `0 K` when computed (a static DFT calculation), `room temperature` when measured; a property that is itself a temperature (a melting point) holds at that temperature |
| pressure | `ambient pressure` |
| structure | the kind of compound, from its composition (not an assumption, but not a crystal structure either) |

These are defaults, not statements of the paper. On 208 solid-electrolyte papers they are a large
part of the activation-energy table: 72% of the temperatures, 91% of the transport components, 99%
of the pressures and 23% of the origins are assumed, and for 27% of the rows the structure is only
the kind of compound. Every row has its `basis`, and `n_assumed` says how many of its answers are
defaults.

## What each paper is: `papers.csv`

A PDF says little about itself reliably: its embedded title can be the file name of a typesetter
("SpringerNature_NatCommun_77363_AIP"), its subject field a sentence of the abstract, and the first
DOI printed in it one of its references. So each paper is looked up in
[OpenAlex](https://openalex.org), the open index of the scholarly literature — by the DOI found in
it, by its arXiv id, else by its title — and a work is accepted only if its own title is printed on
the first page of the PDF (which also throws out a DOI that belonged to a reference). The title,
authors, journal, DOI, year, OpenAlex id and license of the matched work then replace what the
PDF guessed. `metadata_basis` says where the description of each paper comes from:

| `metadata_basis` | |
|---|---|
| `OpenAlex (by its DOI; its title is printed on the first page)` | (or `by its arXiv id`, `by its title`) the work was found and checked |
| `the PDF itself (no OpenAlex work matches it)` | nothing matched: what the PDF gives stands; what it does not give says so ("not printed in the PDF's metadata") |
| `the PDF itself (OpenAlex could not be reached when it was read)` | the network was down: run again with `--rebuild` to complete it |
| `the PDF itself (OpenAlex was not asked)` | run with `--offline` |
| `OpenAlex (by the DOI its source reported)` | a paper of the web project whose PDF is an author manuscript, its title a little different from the published one: the DOI its source reported names it |
| `the source it was fetched from (openalex)` | a paper of the web project: what its source reported, completed from OpenAlex where it lacked something |

The provenance columns of a PDF of this computer describe the file itself: `source_service` =
`a file of this computer`, `source_url` its path, `retrieved_at` its date, `file_sha256` its checksum.

What was found is kept in `metadata_cache.json` in the database folder, by the checksum of each
PDF: a rebuild does not ask again, and keeps what an earlier run found even if OpenAlex cannot be
reached at that moment. (A request that fails is asked again; when a service is down, the papers
read in the next minute are not held up by it.) `OPENALEX_API_KEY` and `MME_EMAIL`, when
set, are sent along.

## How materials are found and tied to values

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

## A database made by an earlier version

The tables of this version have other columns than before (the tables of the transport
quantities, the `metadata_basis` of the papers, `summary.csv` in place of the wide
`database_summary.csv`, …). New papers cannot be added to an older database, so it is rebuilt by
itself the next time the command runs: its files are moved to a `previous_<date>/` folder inside
the results folder — nothing is deleted, nothing is downloaded again — and the PDFs are read again.
To rebuild a database of this version (after the PDFs changed, say), add `--rebuild`:

```bash
python -m LocalExtraction --rebuild                    # your own PDFs
python -m WebScraping --stage extract --rebuild        # the web papers (nothing is fetched)
```

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
- **OCR quality depends on Tesseract being installed** (`brew install tesseract` /
  `sudo apt install tesseract-ocr`); without it, image-only/scanned pages silently fall back to
  the (near-empty) native text layer instead of erroring.

## Tests

```bash
python -m pytest LocalExtraction      # or: python -m unittest discover -s LocalExtraction/tests -t . -v
```

`tests/test_extraction.py` checks, on sentences, which numbers are read as which quantity, which
material each is tied to and where its context comes from — and, on a PDF run through the whole
pipeline, that no table of the database has an open cell; `tests/test_cli.py` checks the command;
`tests/test_gui.py` builds the window (transparent, on a made-up database) and drives it — without
a screen those tests are skipped.
