# Crystal and Structure Classification — Part 4

A part of [MoukhlijMatExtract (MME)](../README.md) · Author: Younes Moukhlij

Sorts the materials of both databases two ways and writes **one database per class**: by **known
crystal family** (NASICON, garnet, argyrodite, …) and by **structure family** (oxide, sulfide,
halide, …). Every material is in one structure family; a material of none of the known crystal
families says so (`no known crystal family`, with why and its composition type) instead of being
put in a made-up class. Each row says how its classes were decided.

| | |
|---|---|
| **Input** | the databases `LocalExtraction/local_output/` and `WebScraping/web_output/` (whichever exist) |
| **Output** | `crystal_structure/`, `structure_families/` and `all_materials.csv`, in this folder |
| **Uses** | the chemistry of [LocalExtraction](../LocalExtraction/README.md) (`chemistry.py`): keep the two folders side by side |

| Folder | Classified by | Classes |
|---|---|---|
| `crystal_structure/` | the known crystal family the material belongs to | NASICON, LISICON, thio-LISICON, garnet, argyrodite, perovskite, anti-perovskite, spinel, olivine, layered, rock-salt, anti-fluorite (and fluorite, wurtzite, zinc-blende, tavorite when a paper states them) — and the two states of no crystal structure, amorphous and glass-ceramic. Only these: a type named after a compound (LGPS-type, Li3YCl6-type, Li3InCl6-type, UCl3-type, Na3PS4-type, …) is no family, nor is a composition type (`A3MX6 halide`) |
| `structure_families/` | the family of compounds, after its anions | oxide, sulfide, selenide, halide, oxyhalide, nitride, phosphide, hydride, element_or_alloy |

## Set up (once)

The whole project works inside one virtual environment (venv), `.venv/` in the project folder.
From the project folder (the one that holds `Crystal and Structure Classification/`), with Python
3.11 or newer:

```bash
python3 -m venv .venv                     # create the venv, once
source .venv/bin/activate                 # enter it (Windows: .venv\Scripts\activate)
pip install -r requirements.txt           # install the packages inside it
python -m spacy download en_core_web_sm   # and the language model (for parts 1 and 2)
```

Then work inside it: enter it (`source .venv/bin/activate`) in every new terminal before you run
the commands below; your prompt then starts with `(.venv)`. The
[main README](../README.md#install-once) has the whole setup.

## Run it

From the project folder, inside the venv — the folder's name has spaces, so it is run as a folder,
in quotes:

```bash
python "Crystal and Structure Classification"                                   # both databases
python "Crystal and Structure Classification" --source WebScraping/web_output   # one database only
python "Crystal and Structure Classification" --out some/folder                 # write somewhere else
python "Crystal and Structure Classification" gui                               # the window (see below)
```

Run it again after an extraction: the two class folders are written anew (a class left with no
material disappears). The databases it reads are never changed.

## What it writes

```
Crystal and Structure Classification/
├── all_materials.csv              every material with its two classes and why
├── crystal_structure/
│   ├── summary.csv                one line per class: materials, papers, activation energies, lowest Ea —
│   │                              and the bulk, grain-boundary and total activation energies apart
│   ├── activation_energy_by_component.csv   per class and component: count, lowest (whose), median, highest
│   ├── crystal_structure.xlsx     the summary, the activation energies by component and one sheet per class
│   ├── NASICON/
│   │   ├── materials.csv                 its materials, lowest activation energy first
│   │   ├── activation_energy.csv         every activation energy of them (with `database`, `crystal_structure`, `structure_family`)
│   │   ├── ionic_conductivity.csv        every ionic conductivity of them
│   │   ├── electronic_conductivity.csv   every electronic conductivity of them
│   │   ├── diffusion_coefficient.csv     every diffusion coefficient of them
│   │   ├── properties.csv                every value of them, of any property
│   │   ├── papers.csv                    the papers they come from
│   │   ├── bulk/                         sub-class: NASICON for bulk transport — the same files, bulk values only
│   │   ├── grain_boundary/               sub-class: NASICON for grain-boundary transport
│   │   └── total/                        sub-class: NASICON for the transport of the whole sample
│   └── garnet/   argyrodite/   thio-LISICON/   amorphous/   ...   (the same files; known families only)
└── structure_families/
    ├── summary.csv   structure_families.xlsx
    └── oxide/   sulfide/   halide/   oxyhalide/   ...   (the same files)
```

A class folder has the shape of the databases it was read from, so the ranking reads it too —
the best garnets, the best sulfides:

```bash
python -m SelectingTopMaterial --source "Crystal and Structure Classification/crystal_structure/garnet" --out garnet_ranking
```

`materials.csv` has one line per material (one composition, whatever the spelling or the paper):
its two classes and their `*_basis`, what its papers state (`structure_types_stated`, crystal
systems, polymorphs, space groups), how many papers and from which database, its activation
energies (count, min, median, max) — and the lowest bulk, grain-boundary and total one apart
(`Ea_bulk_min_eV`, `Ea_grain_boundary_min_eV`, `Ea_total_min_eV`, with their counts) — and its
highest ionic conductivity.

## Bulk, grain boundary, total

An activation energy describes ion transport inside the grains (**bulk**), across the boundaries
between them (**grain boundary**), or through the whole sample (**total**, what a pellet's impedance
gives when its parts are not separated); the extraction records which in `transport_component`, for
the conductivities and diffusion coefficients too.

**Every class has three sub-classes**, one per component:

```
crystal structures:                       structure families:
                 ├─ bulk                                   ├─ bulk
    NASICON ─────┼─ grain boundary            oxide ───────┼─ grain boundary
                 └─ total                                  └─ total
```

In the files, a sub-class is a folder inside its class's — `NASICON/bulk/`,
`NASICON/grain_boundary/`, `NASICON/total/` (and `surface/` for a class with a surface value) — and a
database of its own: the values of that component only (its activation energies, ionic and
electronic conductivities and diffusion coefficients), the materials they are of (`materials.csv`,
with `transport_component`, their values of that component and the papers that report them) and
those papers. A class with no value of a component still has that sub-class, empty: its tables have
their headers and no row, and `activation_energy_by_component.csv` says `no grain-boundary activation
energy reported`. (A database of an earlier version, which does not record the component, gives
empty sub-classes.) The terminal shows the tree:

```
    NASICON                        46 materials    33 Ea    41 papers
      ├─ bulk                       8 materials    14 Ea  lowest 0.1275 eV (Na3.7Mg0.15Zr1.45Sc0.4Si2PO12)
      ├─ grain-boundary             0 materials     0 Ea  no activation energy
      └─ total                      9 materials    19 Ea  lowest 0.1 eV (Na3Zr2Si2PO12)
```

Being databases too, sub-classes can be ranked on their own:

```bash
python -m SelectingTopMaterial --source "Crystal and Structure Classification/crystal_structure/NASICON/bulk" --out nasicon_bulk
```

Each class's activation energies are also counted and compared per component:

| File | What |
|---|---|
| `summary.csv` (each axis) | per class: `n_Ea_bulk`, `Ea_bulk_min_eV`, `Ea_bulk_min_material`, `Ea_bulk_median_eV`, and the same for `grain_boundary` and `total` (`no … value reported` when the class has none) |
| `activation_energy_by_component.csv` (each axis) | every class with its sub-classes under it — NASICON bulk, NASICON grain boundary, NASICON total, … , one line each: `n_values`, `n_materials`, `min_eV`, `min_material`, `median_eV`, `max_eV`, `n_component_stated` / `n_component_assumed`, and the sub-class's `folder` |
| `materials.csv` (each class), `all_materials.csv` | per material: `n_Ea_bulk`, `Ea_bulk_min_eV`, … |

**Stated or assumed.** Few papers say in so many words which component a value is; when the sentence
does not, the extraction gives the likeliest one and says why in its `basis` ("assumed (simulated in
a bulk cell)", "assumed (measured on a pellet: …)"). `n_component_stated` counts the values whose
component the paper itself states; the window can count only those.

## The window

```bash
python "Crystal and Structure Classification" gui        # or: make classify-gui
```

It classifies the databases when it opens — and writes the class folders, as the command does
(untick *write the class folders* to only look; `--no-write` from the terminal).

- **Two tabs**, *Crystal structures* and *Structure families*, each a **tree of the classes and
  their sub-classes**: NASICON, and under it *bulk*, *grain boundary* and *total* — every class has
  the three. Each line gives its materials, papers and activation energies, the lowest (and whose),
  the median, the highest, and how many of them the paper states the component of (— where there is
  none). Click ▸ to open or close a class, *Open / Close every class* for all of them; click a
  heading to sort the classes by it.
- **Select a class** to list its materials below; **select a sub-class** (NASICON → bulk) to list the
  materials of that class with a bulk activation energy, the lowest bulk value first.
- **Classes: side by side** shows instead one line per class with the bulk, grain-boundary and total
  values in columns next to each other.
- The **materials** list shows each one with its lowest bulk, grain-boundary and total value, how its
  structure is known and its highest ionic conductivity. *Find a material* narrows the list.
- **Double-click a material** for every activation energy of it: the value, the component and
  whether the paper states it or it was assumed, measured or computed, the paper's own result or a
  cited one, where in which paper it was read, and the sentence.
- **Which activation energies count**: measured and computed, or one of them; the papers' own
  results only (not the values they cite); only those whose component the paper states. Every
  number of the window follows the choice; the files written are those of the command (all values).
- **Databases**: the two extractions' folders, ticked when they exist; *Add a database…* for
  another one (a class folder of an earlier run too).

## How a class is decided

**Crystal structure**, in this order — the first that answers decides, and `crystal_structure_basis`
says which:

1. **The composition**, where it leaves no doubt: Li7La3Zr2O12 and its doped variants are garnets,
   Li6PS5X argyrodites, A(1+x)M2(PO4)3 NASICONs … (the rule the extraction itself uses,
   `LocalExtraction/chemistry.py`, `structure_family`). Basis: `known for this composition`. The
   rule also knows Li10GeP2S12 as LGPS-type — a structure of its own, not a family: such a material
   is given no family from its formula or its analogues (steps 5 and 7), only from what its papers state.
2. **A composition series** taken at its nominal value: Li1+xTi2-xAlx(PO4)3 at x = 0.25 is a NASICON.
3. **What its papers state** ("NASICON-type", "the garnet LLZO"): the type stated by the most
   papers, if at least a third of the material's papers state it. Basis: `stated by 1 of the 3 paper(s)`.
4. **A glassy state** (glass, amorphous, glass-ceramic), if most of its papers state it: a glassy
   sample in one paper does not make the material a glass.
5. **The family of its composition type**: a lithium-rich A3–4MX4 orthooxide (Li3PO4, Li4SiO4)
   is LISICON, its sulfide (Li3PS4, Li4GeS4) thio-LISICON. Basis: `inferred: the family of its
   composition type …`. ("Layered", said of a Li3MX6 halide, describes the stacking of its anions,
   not the family of the layered oxides, and is not taken for one.)
6. **A family or a state stated by fewer of its papers** than in steps 3 and 4. Basis: `stated by only 1 of the 13 paper(s)`.
7. **Its analogues** — the doped or substituted variants of a material classified by steps 1–5:
   the same family and stoichiometry (A, M and X per formula unit within 15%), the same anions and
   mobile cations, the same polyanion centres (P, Si, Ge, …) and a main framework cation in common —
   when at least two thirds of them agree on a family. A state (amorphous, glass-ceramic) is never
   handed on. Basis: `inferred: the type of its analogues …`. So a doped spinel is a spinel, but
   ZrO2 is not a NASICON like a zirconium phosphate.
8. **Otherwise: `no known crystal family`.** Its basis says why — none of the known families is
   stated by its papers, known for its composition or shared by its analogues — what it is (its
   composition type, an element, an intermetallic, a mixture whose shares are open), and a type named
   after a compound its composition or its papers give (`LGPS-type`, `Li3YCl6-type`). It is in no
   folder of `crystal_structure/`, and in its folder of `structure_families/`. Its composition type
   (`A3MX6 halide`: the formula it shares with its kind, A the mobile cations, M the other cations,
   X the anions) is the column `composition_type` of every material.

Where the papers disagree with the class, the basis says so ("…; the papers also state perovskite").
To keep only the classes the papers or the compositions establish, drop the rows whose basis
starts with `inferred`.

**Structure family**: always from the composition, after its anions (`compound_class` in
`LocalExtraction/chemistry.py`), then grouped:

| Family | Compounds |
|---|---|
| oxide | oxides, phosphates, silicates, borates, sulfates, carbonates, oxynitrides (LiPON) |
| sulfide | sulfides, thiophosphates (Li6PS5Cl, Li10GeP2S12, Li3PS4) |
| selenide | selenides, selenophosphates |
| halide | chlorides, bromides, iodides, fluorides, mixed halides (Li3YCl6, Li3InCl6) |
| oxyhalide | oxygen and a halogen as anions (Li3OCl, LiNbOCl4) |
| nitride | nitrides |
| phosphide | phosphides, arsenides (Li3P, Li8SiP4) |
| hydride | hydrides, borohydrides, closo-borates (LiBH4, Na2B12H12) |
| element_or_alloy | no anion: metals and alloys |

The kind of compound is kept in `compound_class` (thiophosphate, chloride, phosphate, …).

## Tests

```bash
python -m pytest "Crystal and Structure Classification"
```

They run on small made-up databases in a temporary folder and never read or write the project's
own databases.
