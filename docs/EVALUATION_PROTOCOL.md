# Evaluation protocol — garnet and NASICON solid electrolytes

Written on 2026-11-14, **before** any paper of this evaluation is drawn or looked at. Nothing in it may change
after the draw. A change made later is reported as a deviation, with its reason.

## 1 · What is measured

How well MoukhlijMatExtract extracts, from legally obtained papers on garnet and NASICON solid electrolytes:

- the **activation energy** (Ea) of ion transport;
- the **ionic conductivity** (σ) and the temperature it was measured at;
- the **diffusion coefficient** (D).

For each property:
- **precision** — the share of extracted values that are right;
- **recall** — the share of the values the papers report that were extracted;
- **F1**.

Each is given with a 95 % interval (Wilson for proportions, bootstrap over papers for F1, seed 20261114).
Precision is reported **per field**, so a reader sees which part fails:

| Field | Right when |
|---|---|
| number | the value and its unit, after conversion, match the paper within 1 % (or the paper's last digit) |
| material | the stored formula is the sample the value belongs to. A doped sample stored under its parent formula (Li7La3Zr2O12 for a Ta-doped sample) is **wrong** |
| component | bulk, grain boundary or total, as the paper states; "assumed" counts as right only if the paper does not say |
| origin | experimental or computed |
| energy kind, attribution, mobile ion | `energy_kind`, this work / cited, the ion: the fields the article's ranking filters on. The workbook has no correction column for them yet (audit finding N-15): until it has, a wrong one is marked `partly` with `error_type` "kind", "attribution" or "ion" and the right answer in `note` |

A value is **fully correct** only when every field is right. That headline figure is the one compared with the earlier
audit's 41 % (Wilson 31–52 %, held-out round G of 2026-11-11, all solid electrolytes).

## 2 · Code and data

- **Code:** the commit tagged for the article (for example `v1.2.0`). It is recorded in `run_manifest.json`, with
  `uncommitted_changes: false`. No rule is changed between the extraction and the scoring.
- **Database:**
  - rebuilt from `~/MoukhlijMatExtract/WebScraping/papers_garnet_nasicon` alone, into `web_output_garnet_nasicon`
    (`mme-local extract … --rebuild`, metadata lookup on);
  - legal copies only (`mme-release` leaves out the rest).
- **Language model:** `en_core_web_sm 3.8.0`, recorded per paper (`extracted_with`).

## 3 · Held-out papers

Papers used before to develop or check the rules are left out of the draw:
- `~/MoukhlijMatExtract-audit/p4/dev_papers.txt` and `test_papers.txt`;
- the papers of `eval/sampleE.csv`, `sampleF1.csv`, `sampleF2.csv`, `sampleG1.csv` and `sampleG2.csv`.

Before the draw, `scripts/audit/heldout_source.py` writes `Evaluation/heldout_source/`:
- **what it is:** a copy of the rebuilt database without those papers;
- **what it lists:** the papers left out, with the file they were found in.

The draw reads that copy only.

## 4 · Draw and sample size

- **Draw:** `mme-eval sheet --source Evaluation/heldout_source --papers 60 --seed 20261114
  --out Evaluation/annotation_A.xlsx`.
  - The draw takes papers with and without extracted values alike, so that recall counts the values the tool
    missed.
  - Only papers with a recorded legal copy are drawn (the default; `--all-papers` is not used).
- **Size:** 60 papers. The garnet/NASICON corpus gives about 1.1 activation energies per paper over all papers
  (737 values in 647 papers), and 3.5 per paper that has one. 60 papers give about 70 Ea values, plus the σ and D
  values. At p = 0.5 that is a 95 % half-width of about ±12 points for Ea precision. ±10 points needs about 96
  values: if the first 60 papers give fewer than 96 Ea values, draw 30 more with the same seed (the next papers of
  the same draw), decided now, not after looking.

## 5 · Annotation

- **Annotator A** (the author) annotates all 60 papers in `annotation_A.xlsx`. For each paper, A:
  1. reads the whole PDF, tables and captions included;
  2. writes in the Missed sheet every Ea, σ and D that the paper reports and that the Values sheet does not have;
  3. sets each extracted value's `verdict` (correct / partly / wrong) and fills the `true_…` columns.

  Reading the paper before the extracted values limits anchoring on what the tool found.
- **Annotator B** (a colleague in solid-state ionics, not involved in the code):
  - annotates 12 of the 60 papers (20 %), drawn with seed 20261115, in a copy of the workbook
    (`annotation_B.xlsx`);
  - does so independently, without seeing A's answers.
- **Agreement:** `mme-eval agree Evaluation/annotation_A.xlsx Evaluation/annotation_B.xlsx`, reported as Cohen's κ
  per field. If κ < 0.6 on a field, A and B settle the differences and refine the guideline below. The settled
  version is used, and both κ (before) and the changes are reported.
- **Expected time:**
  - about 15–20 min per paper for a full annotation (every Ea, σ and D of the paper) — 60 papers take 15–20 hours
    for A;
  - about 3–4 hours for B.

### Guideline (what counts)

- **Ea:**
  - Count every value the paper reports for ion transport in a material.
  - An Arrhenius slope of conductivity or diffusion, a computed migration barrier and an NMR activation energy all
    count, each with its kind.
  - These are **not** an Ea of the material:
    - a difference between two energies ("0.06 eV lower than …");
    - a reaction or formation energy;
    - a charge-transfer (interfacial) energy;
    - a value only cited from another paper (count it with attribution "cited").
- **σ:** the value and its temperature. "Room temperature" is written as such; 25 °C and 298 K are the same.
  Total, bulk and grain-boundary values are separate.
- **D:** the value, its kind (tracer, chemical, self, from NMR/MD) and its temperature.
- **Material:** the exact sample. For a series ("x = 0.2–0.6"), each member that has its own value. Composites and
  polymer electrolytes are written as such (PEO–LLZO), never as their ceramic.
- **Ranges:**
  - "0.30–0.35 eV" for one sample is one value with its range, recorded as the paper gives it.
  - The tool stores two values. The scoring counts the pair as one value, right when both ends are.
- **Units:** as printed; the scoring converts.

## 6 · Scoring

```
mme-eval score --gold Evaluation/annotation_A.xlsx --source Evaluation/heldout_source --seed 20261114 \
               --out Evaluation/scores
```

**Baseline:** ChemDataExtractor on the same 60 PDFs (`Evaluation/baselines/chemdataextractor_baseline.py`), scored
with `--predictions`. It gives a paired comparison on the same papers.

**Reported:**
- precision, recall and F1 per property and per field, with intervals;
- κ per field;
- the CDE comparison;
- the five most frequent error causes, each with its count.

**Deposited with the dataset:** the workbooks, the scores and this protocol (`mme-release --with Evaluation`).

## 7 · What the result can support

| Fully correct Ea (lower bound of the 95 % interval) | What the article can claim |
|---|---|
| ≥ 80 % | The extracted values can be ranked directly; the ranking is reported with its uncertainty |
| 50–80 % | The extraction finds candidates; every value in the ranking is checked by hand before it is used |
| < 50 % | The extraction is a search aid; the ranking is built from checked values only |

The earlier figure (41 %, 31–52 %) is in the last row. If the ranking is built from values checked by hand, the
dataset must say which values were checked. It has no column for that yet, so add one before the release.
