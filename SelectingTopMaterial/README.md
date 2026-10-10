# SelectingTopMaterial

Reads the activation energies AutoMatExtract extracted and ranks the materials by them.

| Activation energy | Class |
|---|---|
| Ea < 0.25 eV | **Superionic** |
| 0.25 ≤ Ea < 0.30 eV | **Performant** |
| 0.30 ≤ Ea < 0.40 eV | **Acceptable** |
| Ea ≥ 0.40 eV | Rejected |

Every limit is exclusive: a material at exactly 0.25 eV is Performant, one at exactly 0.40 eV is
Rejected.

It only reads the results folders (`local_output/`, `web_output/`, `output/`) and writes into its
own `SelectingTopMaterial/results/`. It imports nothing from the rest of the project and changes
none of its files.

## Run it

From the project folder:

```
python -m SelectingTopMaterial
```

(`python SelectingTopMaterial` does the same.) It needs Python 3.11 or later and nothing beyond
what the project already installs; only the Excel workbook needs `openpyxl`, and the other files
are written without it.

The terminal shows what was read, how many materials each class holds, and the materials that
pass, best first. The same ranking is written to `SelectingTopMaterial/results/`:

| File | What it holds |
|---|---|
| `top_materials.csv` | The materials that pass (Superionic, Performant, Acceptable), lowest Ea first |
| `all_materials.csv` | Every material with its class, the rejected ones too |
| `values.csv` | Every activation energy behind them, with its own class, its paper, page and sentence |
| `selection.xlsx` | The three tables and the rule, in one workbook |
| `selection.json` | Everything, nested: each material with its values |
| `report.html` | The ranking as a page: a chart of every material against the limits, and a table where each material opens onto the values it stands on |

## How a material gets its class

**One material, one composition.** The values are grouped by composition, so
`Li1.3Al0.3Ti1.7(PO4)3` and `Li1.3Ti1.7Al0.3(PO4)3` are the same material, in whatever paper
they appear. With `--by-phase`, the phases the database names are ranked apart:
`Li7La3Zr2O12 (cubic)` and `Li7La3Zr2O12 (tetragonal)`, `Li3PS4 (β-phase)` and `Li3PS4 (γ-phase)`.

**One material, one Ea.** A material often has several activation energies. Which one stands for
it is the *policy*:

| Policy | The Ea of a material is |
|---|---|
| `consensus` (default) | the confidence-weighted median of its values: one outlier does not decide |
| `optimistic` | its lowest reported value |
| `conservative` | its highest reported value |

**Each paper counts once.** When two results folders hold the same paper (`output/` is often an
earlier copy of `local_output/`; an article can be in `papers/` and fetched from the web too),
its values are taken from the first folder only. Papers are matched by DOI when `papers.csv` has
it, by file name otherwise. A value a paper repeats (abstract, then text) counts once.

**What is unsure is written, not hidden.** The `checks` column says `ok`, or what to look at
before trusting the class:

| Check | Meaning |
|---|---|
| `borderline (0.25 eV limit)` | The Ea is within 0.01 eV of a limit |
| `values disagree (Superionic to Rejected)` | The material's values fall on both sides of a limit; `class_of_values` gives the count in each class |
| `low confidence` | The mean extraction confidence of its values is below 0.5 |

A check never moves a material to another class.

## The columns

`top_materials.csv` and `all_materials.csv`:

| Column | Meaning |
|---|---|
| `rank` | 1 is the lowest activation energy |
| `material`, `class` | The material and the class its Ea earns |
| `activation_energy_eV` | The Ea that stands for the material (see the policy) |
| `Ea_min_eV`, `Ea_max_eV` | Its lowest and highest reported values |
| `n_values`, `n_papers` | How many values, from how many papers |
| `class_of_values` | How its values spread over the classes: `Superionic 2 \| Rejected 1` |
| `checks` | `ok`, or the checks above |
| `confidence` | Mean extraction confidence of its values |
| `structure`, `data_origin`, `transport_component`, `attribution`, `temperature` | What its values say of each; when they differ, each answer with its count: `simulation (2) \| experimental (1)` |
| `papers` | The papers its values come from |
| `source_paper`, `source_page`, `source_sentence` | Where the reported value closest to its Ea was read |

`values.csv` has one line per activation energy: the material it counts for, the value and its
own class, then the columns of the database (`reported_as`, structure, temperature, pressure,
origin, component, attribution, confidence, paper, title, DOI, year, page, source, sentence) and
the folder it was read from.

No cell is empty: what the database does not say is written `not reported`.

## Options

```
python -m SelectingTopMaterial --origin experimental     measured values only
python -m SelectingTopMaterial --origin simulation       computed values only
python -m SelectingTopMaterial --attribution this-work   the papers' own results, not what they cite
python -m SelectingTopMaterial --component bulk          one transport component
python -m SelectingTopMaterial --element Na              the sodium conductors
python -m SelectingTopMaterial --min-confidence 0.5      leave out the least sure extractions
python -m SelectingTopMaterial --policy conservative     a material is as good as its worst value
python -m SelectingTopMaterial --by-phase                the phases of a composition apart
python -m SelectingTopMaterial --source web_output       one results folder (several: the most trusted first)
python -m SelectingTopMaterial --top 10 --open           the first ten, and the report in the browser
python -m SelectingTopMaterial --no-files                show the ranking, write nothing
python -m SelectingTopMaterial --out some/folder --format csv html
```

`--help` lists them all. The command ends with 0 when a ranking was written, 1 when there was
nothing to rank or a file could not be written, 2 when it was asked something it cannot do.

## Changing the rule

The classes are in [criteria.toml](criteria.toml), not in the code: the limits, the names, the
default policy and what the checks are held to. Edit that file, or keep it and write another:

```
python -m SelectingTopMaterial --criteria my_criteria.toml
```

Classes are listed best first with rising limits; a file that breaks that is refused with the
reason. Decimals are written with a point (`0.25`).

## From Python

```python
from SelectingTopMaterial import PROJECT_ROOT, Criteria, Filters, discover, select_from

ranking = select_from(discover(PROJECT_ROOT), Criteria.load(), filters=Filters(origin="experimental"))
for material in ranking.top:
    print(material.rank, material.material, material.energy_class.name, material.energy_eV)
```

## Tests

```
python -m unittest discover -s SelectingTopMaterial/tests -t .
```

(or `pytest SelectingTopMaterial`). They run on small made-up databases in a temporary folder and
never read or write the project's own results.

## The files

| File | Role |
|---|---|
| `criteria.toml`, `criteria.py` | The classes and their limits; which class an energy belongs to |
| `loader.py` | Reads `activation_energy.csv` and `papers.csv` of each results folder; each paper once |
| `selection.py` | Groups the values by material, picks the Ea of each, classes and ranks them |
| `models.py` | A value, a ranked material, the whole ranking |
| `console.py` | What the terminal shows |
| `exporters.py` | The CSV, Excel and JSON files |
| `html_report.py`, `report_template.html` | The report page |
| `palette.py` | The colours of the classes in the workbook and the report |
| `cli.py`, `__main__.py` | The command line |
