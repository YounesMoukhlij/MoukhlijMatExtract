# Crystal and Structure Classification — Part 4

A part of [MoukhlijMatExtract (MME)](../README.md) · Author: Younes Moukhlij

Sorts the materials of both databases two ways and writes **one database per class**. Every
material is in one class of each kind — none is left unclassified — and each row says how its class
was decided.

| | |
|---|---|
| **Input** | the databases `LocalExtraction/local_output/` and `WebScraping/web_output/` (whichever exist) |
| **Output** | `crystal_structure/`, `structure_families/` and `all_materials.csv`, in this folder |
| **Uses** | the chemistry of [LocalExtraction](../LocalExtraction/README.md) (`chemistry.py`): keep the two folders side by side |

| Folder | Classified by | Classes |
|---|---|---|
| `crystal_structure/` | the structure type the material crystallises in | NASICON, LISICON, thio-LISICON, garnet, argyrodite, LGPS-type, perovskite, anti-perovskite, spinel, olivine, layered, rock-salt, anti-fluorite, Li3YCl6-type, Li3InCl6-type, Li3YbCl6-type, UCl3-type, Li7P3S11-type, Na3PS4-type, amorphous, glass-ceramic — and, in `composition_types/`, the materials of no named type, by their composition type (`A3MX6 halide`, `AMX3 oxide`, …) |
| `structure_families/` | the family of compounds, after its anions | oxide, sulfide, selenide, halide, oxyhalide, nitride, phosphide, hydride, element_or_alloy |

## Run it

From the project root — the folder's name has spaces, so it is run as a folder, in quotes:

```bash
python "Crystal and Structure Classification"                                   # both databases
python "Crystal and Structure Classification" --source WebScraping/web_output   # one database only
python "Crystal and Structure Classification" --out some/folder                 # write somewhere else
```

Run it again after an extraction: the two class folders are written anew (a class left with no
material disappears). The databases it reads are never changed.

## What it writes

```
Crystal and Structure Classification/
├── all_materials.csv              every material with its two classes and why
├── crystal_structure/
│   ├── summary.csv                one line per class: materials, papers, activation energies, lowest Ea
│   ├── crystal_structure.xlsx     the summary and one sheet per class
│   ├── NASICON/
│   │   ├── materials.csv                 its materials, lowest activation energy first
│   │   ├── activation_energy.csv         every activation energy of them (with `database`, `crystal_structure`, `structure_family`)
│   │   ├── ionic_conductivity.csv        every ionic conductivity of them
│   │   ├── electronic_conductivity.csv   every electronic conductivity of them
│   │   ├── diffusion_coefficient.csv     every diffusion coefficient of them
│   │   ├── properties.csv                every value of them, of any property
│   │   └── papers.csv                    the papers they come from
│   ├── garnet/   argyrodite/   LGPS-type/   Li3YCl6-type/   ...
│   └── composition_types/
│       └── A3MX6 halide/   AMX3 oxide/   ...   (the same files)
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
systems, polymorphs, space groups), how many papers and from which database, and its activation
energies (count, min, median, max) and highest ionic conductivity.

## How a class is decided

**Crystal structure**, in this order — the first that answers decides, and `crystal_structure_basis`
says which:

1. **The composition**, where it leaves no doubt: Li7La3Zr2O12 and its doped variants are garnets,
   Li6PS5X argyrodites, A(1+x)M2(PO4)3 NASICONs, Li10GeP2S12 LGPS-type … (the rule the extraction
   itself uses, `LocalExtraction/chemistry.py`, `structure_family`). Basis: `known for this composition`.
2. **A composition series** taken at its nominal value: Li1+xTi2-xAlx(PO4)3 at x = 0.25 is a NASICON.
3. **What its papers state** ("NASICON-type", "the garnet LLZO"): the type stated by the most
   papers, if at least a third of the material's papers state it. Basis: `stated by 1 of the 3 paper(s)`.
4. **A glassy state** (glass, amorphous, glass-ceramic), if most of its papers state it: a glassy
   sample in one paper does not make the material a glass.
5. **A prototype**, from its composition type and the symmetry its papers state: an A3MX6 halide
   is Li3YCl6-type when trigonal (P-3m1), Li3InCl6-type when monoclinic (C2/m), Li3YbCl6-type when
   orthorhombic (Pnma); an AMX4 halide in P63/m is UCl3-type; a lithium-rich A3–4MX4 orthooxide
   (Li3PO4, Li4SiO4) is LISICON, its sulfide (Li3PS4, Li4GeS4) thio-LISICON; a sodium A3MX4
   sulfide (Na3PS4, Na3SbS4) is Na3PS4-type; Li7P3S11 is its own type. Basis: `inferred: the
   prototype of its composition type …`. ("Layered", said of a Li3MX6 halide, describes the anion
   stacking its monoclinic and trigonal phases share and is not taken for a structure type.)
6. **A type or a state stated by fewer of its papers** than in steps 3 and 4. Basis: `stated by only 1 of the 13 paper(s)`.
7. **Its analogues** — the doped or substituted variants of a material classified by steps 1–5:
   the same family and stoichiometry (A, M and X per formula unit within 15%), the same anions and
   mobile cations, the same polyanion centres (P, Si, Ge, …) and a main framework cation in common —
   when at least two thirds of them agree on a type. A state (amorphous, glass-ceramic) is never
   handed on. Basis: `inferred: the type of its analogues …`. So Li3Er0.6In0.4Cl6 is Li3YCl6-type
   like Li3ErCl6, but ZrO2 is not a NASICON like a zirconium phosphate, and Li3ScCl6 is not
   Li3YCl6-type: the Li3MX6 halides change structure with the size of M.
8. **Its composition type** itself (`A3MX6 halide`, `AMX3 oxide`, …: the formula it shares with its
   kind, A the mobile cations, M the other cations, X the anions), in `composition_types/` — or
   `elemental` for an element, `intermetallic` for an alloy, `<family> mixture (shares open)` for a
   mixture whose shares the paper does not give. Basis: `inferred: its composition type …`.

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
