# A literature-scale, traceable database of ion-transport properties of solid electrolytes and electrodes

*Draft of a Data Descriptor (Scientific Data structure). Numbers marked **[run]** come from the final corpus: fill
them from `mme-web coverage`, `make paper` (`tables/database_summary.csv`) and `mme-eval score` after the full
harvest (`mme-web update --all --yes`) and the gold-standard annotation. Numbers without the mark are from the
garnet/NASICON test corpus of November 2026.*

## Abstract

Ion-transport properties (activation energies, ionic and electronic conductivities, diffusion coefficients) decide
which solid electrolytes and electrodes are worth making, but they are scattered across tens of thousands of papers
in prose, tables and captions. We present a database of **[run]** values from **[run]** papers on **[run]**
materials, built with the open-source tool MoukhlijMatExtract from legally obtained full texts only. Each value
carries its unit-converted number, its material and composition, its transport component (bulk, grain boundary,
total), whether it was measured or computed and whether it is the paper's own result or a cited one, the mobile
ion, the kind of activation energy, and its provenance down to the sentence and table cell. Repeated and quoted
values are traced back to one measurement. Accuracy was measured on **[run]** randomly drawn papers annotated by two
people (Cohen's κ = **[run]**), and the annotations are released as a gold standard.

## Background & Summary

- The need: screening of solid electrolytes and electrodes compares Ea and σ across the literature (Bachman 2016;
  Famprikis 2019).
- Existing curated datasets: Liverpool Ionics Dataset (Hargreaves 2023), OBELiX (Therrien 2026) — expert-checked,
  hundreds of materials, Li only, conductivity-centred.
- Auto-generated battery database (Huang & Cole 2020, ChemDataExtractor): broad properties, no transport component,
  no kind of energy, no this-work/cited distinction, no duplicate tracing.
- This database: scale (every family of solid electrolytes, cathodes, anodes), legality (only legal copies;
  `excluded.csv`), traceability (sentence and cell), measured accuracy with a released gold standard, and full
  regeneration from the released code (`make paper`).

## Methods

1. **Corpus.** One job file per domain and per family (24, in `configs/`); keyword searches in 25 services,
   full-text searches in OpenAlex, citation snowballing. Screening by topic and property words.
   Test corpus (garnet/NASICON): 59,023 records → 2,446 proposed → 918 legal copies downloaded.
   Full corpus: **[run]** records → **[run]** proposed → **[run]** downloaded, by publisher in Table **[run]**.
2. **Legal retrieval.** Open-access copies, publisher text-and-data-mining interfaces (Elsevier, Wiley, APS,
   Springer Nature), repositories, arXiv's bulk copy; robots.txt and rate limits respected; the source of every
   PDF recorded (`source_service`, `download_log.csv`).
3. **Extraction.** PDF text, tables and captions (PyMuPDF, Tesseract OCR); sentences (spaCy/scispaCy); quantities
   and units; material resolution (formulas, series, mixtures, paper-defined abbreviations, doped samples);
   context (component, origin, attribution, mobile ion, kind of energy); plausibility and scope checks; the
   `basis` of every answer.
4. **Duplicates.** Same material (by composition), property, component, origin, kind of energy, value within
   tolerance and compatible temperature → one measurement (`measurement_id`, `n_papers_reporting`).
5. **Software and versions.** MoukhlijMatExtract **[version, DOI]**; `requirements.lock`; Docker image; run
   manifests with commit and checksums.

## Data Records

Deposited at Zenodo (**[DOI]**), made by `mme-release`:

| File | Content |
|---|---|
| `activation_energy.csv`, `ionic_conductivity.csv`, `electronic_conductivity.csv`, `diffusion_coefficient.csv` | one row per value, with every column of the data dictionary |
| `papers.csv` | bibliographic record, source of the copy, license, extraction version |
| `materials.csv` | materials with composition and structure family |
| `ranking/`, `classification/` | per-component rankings; classes by structure type and family |
| `data_dictionary.csv`, `README.md` | every column; the datasheet |
| `excluded.csv` | papers left out (no record of a legal source) |
| `run_manifest.json`, `requirements.lock`, `SHA256SUMS` | how it was made |

Counts by property, component and family: Table **[run]** (`make paper` → `tables/database_summary.csv`).
Test corpus: 1,041 activation energies (382 bulk, 33 grain boundary, 618 total) and 3,047 ionic conductivities
from 930 papers.

## Technical Validation

1. **Gold standard.** **[run]** papers drawn at random after the extraction rules were frozen
   (`docs/EVALUATION_PROTOCOL.md`); two annotators; agreement κ = **[run]**. Released separately (`mme-eval gold`).
2. **Precision, recall, F1** per property with 95 % bootstrap intervals, at the value level and the
   value-and-material level (`mme-eval score`): Table **[run]**.
3. **Benchmark** on the same papers: keyword baseline, ChemDataExtractor, an LLM extractor (`mme-eval benchmark`):
   Table **[run]**.
4. **Recall against curated databases** (`mme-eval reference`): OBELiX and the Liverpool Ionics Dataset; the share
   of their entries found only in figures.
5. **Calibration** of the confidence score and the flags (`needs_check`) on the gold standard.
6. **Arrhenius cross-check:** activation energies against the paper's own conductivities at several temperatures.

## Usage Notes

- Filter on `needs_check = no`, `plausibility = in range`, `attribution = this work` and one `transport_component`
  and `energy_kind` before comparing values; never mix bulk and total.
- Use `measurement_id` to count each measurement once; `n_papers_reporting` shows how often a value was quoted.
- The text quoted from papers is included only for openly licensed papers; the provenance (DOI, page, table) of
  every value is always included.

## Code Availability

MoukhlijMatExtract, AGPL-3.0-or-later: https://github.com/YounesMoukhlij/MoukhlijMatExtract (**[release DOI]**).
`make paper` regenerates every table and figure of this descriptor from the deposited data.
