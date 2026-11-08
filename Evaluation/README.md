# Evaluation — how accurate is the extraction?

`mme-eval` (or `python -m Evaluation`) measures how accurately MoukhlijMatExtract extracts **activation
energies, ionic and electronic conductivities and diffusion coefficients**, against values checked by a
person. It reads the databases of parts 1 and 2 and writes into `~/MoukhlijMatExtract/Evaluation/`.

| Input | Output |
|---|---|
| `LocalExtraction/local_output/`, `WebScraping/web_output/` | `Evaluation/annotation.xlsx` (to annotate) |
| the annotated workbook | `Evaluation/scores/report.md`, `metrics.json`, `errors.csv` |

## 1 · Draw the papers — `mme-eval sheet`

```bash
mme-eval sheet                 # 60 papers, seed 7
mme-eval sheet --papers 100 --seed 3 --out Evaluation/second_round.xlsx
```

Papers are drawn **at random from every paper of the databases**, with or without extracted values, so the
recall is measured honestly. The same databases and seed always give the same papers. The workbook
records the date, the software version, the seed and a fingerprint of the databases (About sheet). An
existing workbook is never replaced (`--force` replaces it and keeps the old one as `<name>.<date>.xlsx`).

## 2 · Annotate

Open the workbook; its **Guide** sheet says how. In short, paper by paper:

- **Values** sheet — every value extracted from the paper: `correct`, `partly` (a real value of the paper,
  with a field wrong: write the right one in the `true_` columns) or `wrong` (not a value of this property
  for a material of the paper), and for partly / wrong an `error_type`.
- **Missed** sheet — every value the paper reports that the program did not find, with its unit as written
  (eV, meV, kJ/mol; S/cm, mS/cm, S/m; cm²/s, m²/s).
- **Papers** sheet — `done = yes` when the paper is finished. Only papers marked done are scored; a paper
  marked done with a value left without verdict is left out, and the report says so.

## 3 · Score — `mme-eval score`

```bash
mme-eval score                                   # the values the workbook was made from
mme-eval score --source LocalExtraction/local_output WebScraping/web_output   # a newer run
```

The reference ("gold") values are the rows marked correct, the rows marked partly with their corrections,
and the missed rows. The report gives, for each property and overall:

| Level | A value counts as found when |
|---|---|
| **value** | the paper reports that number for that property |
| **record** | … and for that material (compared by composition: Li6PS5Cl = Li12P2S10Cl2) |

- precision, recall, F1, with **95 % bootstrap intervals** (2,000 resamplings of the papers);
- the accuracy of the **component** (bulk / grain boundary / total) and the **origin** (experimental /
  simulation) of the values found;
- the **calibration** of the confidence column: share of right values per confidence bin, expected
  calibration error, Brier score;
- precision by where the value was read (text or table), and the errors the annotators named;
- `errors.csv`: every false positive and false negative, with its paper, title and sentence.

Two values are the same value within 1 % (or 0.002 eV) for activation energies, and within 2 % on a log
scale for conductivities and diffusion coefficients. Extracted and reference values are paired so that
as many as possible match, each used once.

## 4 · Agreement of two annotators — `mme-eval agree`

Give a copy of the same workbook to a second person (on at least 20 % of the papers), then:

```bash
mme-eval agree Evaluation/annotation_A.xlsx Evaluation/annotation_B.xlsx
```

It gives **Cohen's kappa** of the verdicts on the values both judged, the raw agreement, and the F1 of one
reference set against the other — the numbers a journal asks for to trust the reference set.

## 5 · Other tools on the same papers — `mme-eval score --predictions`

Run another extractor (ChemDataExtractor, an LLM, …) on the PDFs of the annotated papers, write its values
as a CSV with the columns `paper_id` (the PDF file name, as in the workbook), `property`
(`activation_energy`, `ionic_conductivity`, `electronic_conductivity`, `diffusion_coefficient`),
`material`, `value` and — optional — `unit` (as written: meV, mS/cm, …), `component`, `origin`,
`confidence`; then:

```bash
mme-eval score --predictions chemdataextractor.csv llm.csv
```

Each is scored exactly as MoukhlijMatExtract is, and `Evaluation/scores/comparison.md` puts them side by
side, with MoukhlijMatExtract's F1 minus each other's, its 95 % interval and a one-sided p-value from a
**paired bootstrap** (the same resampled papers for both systems).

## 6 · Against curated databases — `mme-eval reference`

```bash
mme-eval reference                      # OBELiX and the Liverpool Ionics Dataset
mme-eval reference --db obelix --limit 50
```

A curated database lists, for the papers it covers, the materials and conductivities careful readers
found. `reference` downloads the databases (at run time, from their publishers: they are not shipped
with MoukhlijMatExtract), fetches the **legal open copies of their papers** into
`Evaluation/reference/papers/` — apart from your databases — extracts them into
`Evaluation/reference/output/`, and looks for every curated entry of a paper it could read among the
extracted ionic conductivities: the same composition, the same value (within 0.1 decade, and within
2 %), a compatible temperature. `reference_report.md` gives the recall of the material and of the
record; `reference_comparison.csv`, every entry and what was found for it. Only recall is measured: a
curated database is not exhaustive, so a value it lacks is not an error.

Many of these papers are not open access: put their PDFs (from your institution) into
`Evaluation/reference/papers/` and run again — they are read too. Each step is skipped when already
done; Ctrl-C keeps what was fetched and extracted.

| Database | License | Cite |
|---|---|---|
| OBELiX | CC BY 4.0 | F. Therrien et al., arXiv:2502.14234 (2025); github.com/NRC-Mila/OBELiX |
| Liverpool Ionics Dataset | academic use with citation; commercial use only under licence | C. J. Hargreaves et al., *npj Comput. Mater.* 9, 9 (2023), doi:10.1038/s41524-022-00951-z |

Some papers cannot be fetched in one run (a site refusing for now, a network outage): the report counts
them as "failed", and running `mme-eval reference` again tries them again.

## 7 · ChemDataExtractor 2 baseline

The toolkit most used to build materials databases from papers (Mavračić et al., *J. Chem. Inf. Model.* 61,
4280 (2021)), given models for activation energies and conductivities the way the battery database of Huang &
Cole (*Sci. Data* 7, 260 (2020)) taught it its properties — `Evaluation/baselines/chemdataextractor_baseline.py`
(in the source code; it imports nothing of MoukhlijMatExtract). It needs older packages, so it runs in its own
environment:

```bash
python3.11 -m venv cde-venv
cde-venv/bin/pip install chemdataextractor2==2.4.1     # large: its neural models are downloaded at first use
cde-venv/bin/python Evaluation/baselines/chemdataextractor_baseline.py <folder of the annotated PDFs> -o cde.csv
mme-eval score --predictions cde.csv
```

On the papers of the curated benchmark (§ 6), the same file scores it beside MoukhlijMatExtract:

```bash
cde-venv/bin/python Evaluation/baselines/chemdataextractor_baseline.py Evaluation/reference/papers -o cde_reference.csv
mme-eval reference --no-fetch --predictions cde_reference.csv
```

It is slow: its BERT model takes about 5 s per paragraph on a laptop CPU (10–30 minutes a paper) and about
3 GB of memory per process. Two papers are read at a time by default (`--jobs`); a paper that takes more than
an hour (`--timeout`) is stopped and reported.

## make

```bash
make eval-sheet PAPERS=60 SEED=7
make eval-score GOLD=Evaluation/annotation.xlsx
make eval-agree FIRST=a.xlsx SECOND=b.xlsx
make eval-score PREDICTIONS="chemdataextractor.csv"
make eval-reference DB=obelix LIMIT=50
```
