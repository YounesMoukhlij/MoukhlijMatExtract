# Known limitations of MoukhlijMatExtract

What the program does not do, or does not do well, with the measurements behind each point. Written for
the users of the data and for reviewers; every number can be reproduced with the commands given
(`mme-eval …`, see `Evaluation/README.md`).

## 1 · Recall against curated databases

`mme-eval reference` looks for every entry of two curated databases of lithium solid electrolytes among
the ionic conductivities MoukhlijMatExtract extracts from the same papers (their legal open copies only).
Measured on 2026-11-08 with version 1.1.0:

| Database | Papers read | Their entries | Material found | Material and value (0.1 decade) | … within 2 % |
|---|---:|---:|---:|---:|---:|
| OBELiX (Therrien et al., 2025) | 27 | 64 | 35.9 % | 12.5 % | 9.4 % |
| Liverpool Ionics Dataset (Hargreaves et al., 2023) | 11 | 48 | 50.0 % | 6.2 % | 2.1 % |

Before the fixes of this version (composition series, σ-subscript headers, S/m units) the same papers gave
28.1 % / 7.8 % / 4.7 % (OBELiX) and 47.9 % / 4.2 % / 0.0 % (Liverpool).

Read these as a lower bound of what any text extractor can reach on these entries, for four reasons:

1. **Values that exist only in figures.** About 40 % of the curated entries of the papers read (47 of 112)
   are not printed in the text, tables or captions as numbers: the curators read them off Arrhenius plots
   (Liverpool records whole temperature series that way). MoukhlijMatExtract reads text, tables and
   captions — not plotted data. Of the 65 entries whose number is printed, 8 are found exactly.
2. **Compositions named otherwise.** A curated entry gives the analysed composition
   ("Li6.46Al0.15La3Zr1.95O11.86"); the paper often names the sample by its nominal formula, a dopant
   ("Al-doped LLZO") or a label. Such entries count as "material not found" even when the value is read.
3. **Tables that lose their layout.** Some PDF tables come out of the PDF with their rows merged into one
   cell (one Wiley table of the benchmark: nine compositions, three columns, in a single cell); their values
   cannot be paired with their rows.
4. **A small sample.** Only 38 of the ~410 papers of the two databases had a legal open copy that could be
   read (307 of the 343 looked for could not be fetched in that run — mostly refusals and a network outage,
   not the absence of a copy: running `mme-eval reference` again tries them again). Putting institutionally
   obtained PDFs into `Evaluation/reference/papers/` widens the sample.

Only recall is measured here: a curated database lists one or a few values per material, so a value it lacks
is not an error. Precision is measured on hand-annotated papers (§ 2).

## 2 · Precision and recall on annotated papers

`mme-eval sheet` draws papers at random from the databases; a person annotates every value (correct /
partly / wrong) and every value missed; `mme-eval score` gives precision, recall and F1 with 95 % bootstrap
intervals, by property, and `mme-eval agree` the agreement of two annotators (Cohen's κ). **These numbers
depend on the annotation and are not in this document**: report them from `Evaluation/scores/report.md`.

## 3 · What is read, and what is not

- **Properties.** Activation energies, ionic and electronic conductivities and diffusion coefficients are
  the quantities checked and ranked; other properties are extracted on a best-effort basis
  (`properties.csv`) and not evaluated.
- **Units.** Energies in eV, meV, kJ/mol, kcal/mol; conductivities in S/cm, mS/cm, µS/cm, S/m, mS/m, µS/m and
  inverse ohms (Ω⁻¹ cm⁻¹, mho/cm); diffusion coefficients in cm²/s and m²/s. A value in another unit, or
  with its unit only in a figure axis, is not read.
- **Composition series.** "Li6+xP1-xGexS5I", and mixtures such as "xLi2S–(100−x)P2S5" or
  "(100−x)(0.75Li2S·0.25P2S5)·xLiBH4", are resolved to one compound when the sentence (or the one before
  it) fixes x, when the paper's own label of the series comes with x, when a sentence pairs several values
  with several x, in a table with a column of x values, and when a sentence fixes x pages after the paper
  named the series, if the paper named only one series that this x fits. Otherwise the series is kept as
  written and never cut down to a compound it is not.
- **The material of a value.** A value is tied to the material its sentence names, or to the one the
  sentences before name. When the sentence names other materials too, the nearest formula wins: in
  "the sample with x = 50 exhibits 1.8 mS cm⁻¹ … than the 75Li2S·25P2S5 glass and the LiBH4 crystal" the
  value goes to LiBH4. A doped sample a paper calls by its parent's name ("the samples" of Fe-substituted
  LLZO) is given to the parent compound. The worked example (`examples/`) shows both cases.
- **Transport component.** Bulk / grain boundary / total / surface is taken from the paper's words and from
  table headers (Ea,bulk, σ gb, σ tot); without them it is assumed (total for a conductivity) and the basis
  column says so. Filter on `n_assumed` before drawing conclusions from a component.
- **Scanned PDFs** are read with OCR (Tesseract), with the usual OCR errors; a PDF with no readable page
  (an incomplete download) is reported as failed, not entered empty.
- **Language.** English papers only.

## 4 · Where the papers come from

The web part downloads only legal copies: open-access copies, and the full texts of Elsevier and Wiley
through their text-and-data-mining APIs when the user's institution subscribes (on its network, or with
Elsevier's institutional token). A PDF put into a papers folder by hand has no record of its source; it is
extracted, but `mme-release` leaves it out of a published dataset unless it is one of the authors' own
(part 1), and leaves out any paper the log of an earlier downloader records as coming from a shadow
library (`excluded.csv` lists them). A curated benchmark therefore covers only the papers with an open copy.

## 5 · Confidence

The `confidence` column is a heuristic score, not a calibrated probability; `mme-eval score` reports its
calibration (expected calibration error, Brier score) on the annotated papers. The `plausibility` column
flags values outside the range known for ion conductors, or carried by electrons rather than an ion; a
flagged value is kept, not removed.

## 6 · Platforms

Tested on macOS (Python 3.13) by hand, and by the continuous-integration tests on Linux (Python 3.11–3.13),
Windows and macOS (Python 3.13). The windows need Tk; on Linux, `python3-tk`.
