# Methods

*Methods section for a journal article on MoukhlijMatExtract (MME). It describes the software as implemented in
version 1.2 (every threshold below is the value in the code). Values marked **[run]** are filled in from the final
corpus and evaluation (`mme-web coverage`, `make paper`, `mme-eval score`, `mme-eval benchmark`). Subsections can be
shortened or moved to the Supplementary Information to fit the target journal.*

---

## 2.1 Overview of the workflow

MME builds a database of ion-transport properties (activation energy *E*ₐ, ionic conductivity σ, electronic
conductivity σₑ and diffusion coefficient *D*) of battery materials from the scientific literature, in six stages
(Fig. 1):

1. **corpus construction:** discovery of candidate papers in bibliographic services and screening for relevance
   (§2.2);
2. **legal acquisition** of the full texts (§2.3);
3. **document processing:** text, tables and captions (§2.4);
4. **information extraction:** quantities, units, materials and context (§2.5–2.7);
5. **quality control:** plausibility, scope, consistency and duplicates (§2.8);
6. **aggregation:** ranking, classification and machine-learning datasets (§2.9).

The accuracy of the extraction was measured on a gold standard annotated by people (§2.10). Every stage records what
it did and from which input (§2.11).

The study covers three domains, each with its own search, database and ranking criteria: solid-state electrolytes,
cathodes and anodes. Within the electrolyte domain, 21 further searches each target one family:
- garnet, NASICON, LISICON, argyrodite, LGPS;
- halide, perovskite, antiperovskite, β-alumina;
- complex hydride, sulfide glass, nitride, fluoride, LiPON;
- polymer, hybrid (polymer–ceramic composites), mixed-anion, multivalent-ion conductors;
- oxides by chemistry and by structure;
- a combined garnet–NASICON search.

> **Figure 1.** Workflow of MME. *Corpus construction* (keyword, full-text and citation searches in 25 services →
> merging by DOI → screening) → *legal acquisition* (17 copy sources) → *document processing* → *extraction* →
> *quality control* → *database* → ranking / classification / ML datasets, with the evaluation against the gold
> standard. *(Draw from the diagram in the README.)*

---

## 2.2 Corpus construction

**Search definitions.** Each search is defined by a job file (YAML) that fixes, for one domain or family:
- the keyword queries;
- the full-text queries;
- the publication years;
- the services queried;
- the screening vocabulary: topic words, property words and excluded words.

The job files are released with the software, so every search can be repeated exactly.

**Keyword search.** Each query was sent to each enabled service, up to 200 results per query and service:
- **indexes:** OpenAlex [@Priem2022], arXiv, Crossref, Semantic Scholar, Europe PMC, OpenAIRE, DOAJ;
- **publishers' and national databases:** J-STAGE, Springer Nature, PLOS, NASA NTRS;
- **repositories:** CORE, Zenodo, DataCite, Figshare, OSF Preprints, LA Referencia, theses.fr;
- **services needing a key:** Scopus, NASA ADS, IEEE Xplore, Web of Science, The Lens, BASE, Dimensions.

Records were restricted to articles, reviews and (optionally) preprints in English within the years of the job. The
same paper returned by several services was merged into one record by its DOI (or arXiv identifier). The record
keeps which services and queries found it.

**Full-text search.** Abstracts often omit the quantities a paper reports. Each job therefore also queried OpenAlex's
full-text index:
- **What it returns:** every work whose full text contains each phrase of a query exactly, for example `"activation
  energy" "ionic conductivity"` (21,951 works) or `"activation energy" "garnet" "ionic conductivity"` (about 2,200).
- **How many:** up to 100,000 works per query.

**Citation snowballing** (optional). For each paper kept, OpenAlex supplied:
- the works it cites (backward);
- up to 100 works citing it, most cited first (forward).

**Screening.** Each record was scored on its title and abstract:

$$ S = 2\,n_{\text{title}} + 1\,n_{\text{abstract}} - 3\,n_{\text{excluded}} $$

- $n_{\text{title}}$ and $n_{\text{abstract}}$ count the topic and property words found, each word counted once,
  in the title if it is there, else in the abstract.
- $n_{\text{excluded}}$ counts the excluded words found.
- A record found by a full-text query is credited with the property words (2 points). Those words are confirmed in
  its full text even when its abstract lacks them.

A paper was proposed for download when all of the following held:
- $S \geq 2$;
- at least one topic word was in its title or abstract;
- at least one property word was found;
- it was not retracted;
- either a legal copy was known, or repositories were to be queried for one.

When a preprint and its journal version were both found, the published version was kept. Proposals can be reviewed
by a person before download. Decisions taken by hand are kept, and they train a classifier whose suggestions are
shown beside the rule-based score; the classifier never overrides the rules.

**Corpus statistics.**
- Test corpus (garnet and NASICON job): 59,023 records screened, 2,446 proposed, 918 copies downloaded.
- Full corpus: **[run]** records → **[run]** proposed → **[run]** downloaded, by publisher in Table S**[run]**.

---

## 2.3 Legal acquisition of full texts

Only legally available copies were retrieved, through the interfaces the providers offer to programs.

**Copy sources.** They were tried in this order, until a valid PDF was obtained:
1. the text-and-data-mining interfaces of Elsevier and Wiley: open-access articles, and subscribed articles within
   the institution's network or with Elsevier's institutional token;
2. the American Physical Society's open-access interface;
3. the open-access locations recorded by OpenAlex and the other search services;
4. Unpaywall;
5. the article's own page at open-access publishers;
6. arXiv;
7. PubMed Central;
8. OSTI.GOV;
9. HAL;
10. Zenodo;
11. DataCite-registered repository copies;
12. Semantic Scholar;
13. NASA ADS;
14. OpenAIRE;
15. CORE;
16. the text-mining links registered with Crossref.

arXiv PDFs were taken first from arXiv's public bulk copy, newest version, and otherwise from arxiv.org.

**Conduct.**
- `robots.txt` (RFC 9309), including `Crawl-delay`, was honoured for every page that is not an API.
- Requests were spaced per host, at each provider's stated rate.
- Back-off on HTTP 429 and 5xx answers.
- A host refusing repeatedly was left alone for the rest of the run.
- No paywall, login, bot check or refusal was bypassed.
- Shadow libraries were not used.

**Validity of a copy.** A file was accepted as the paper only if all of the following held:
- it is a PDF;
- it is not damaged;
- it has at least two pages or 1,500 characters of text;
- for texts of 800 characters or more, its first three pages contain the paper's title.

Scanned PDFs are exempt from the title check.

**Provenance.** For every PDF, the following were recorded in a ledger and in `papers.csv`:
- the source service;
- the URL;
- the licence;
- the retrieval time;
- the SHA-256 checksum.

Papers with no legal copy were listed for manual retrieval. Any PDF lacking a record of a legal source was excluded
from the released dataset (`excluded.csv`).

---

## 2.4 Document processing

**Reading the PDF.**
- **Text:** read in reading order with PyMuPDF.
- **OCR:** a page with fewer than 50 characters of text was treated as a scanned image and read with Tesseract
  [@Smith2007].
- **Sections:** the text was segmented into sections (Abstract, Introduction, Methods, Results, Conclusion,
  References, Supplementary). The section is used in scoring and attribution (§2.7).
- **Tables:** both ruled tables and the unruled ones most journals print were reconstructed. Unruled tables were
  located under their "Table N" caption and their columns recovered from the alignment of the text. Headers split
  over two lines and units in brackets, square brackets or after a slash were joined to their column.
- **Captions** of figures and tables were kept as separate blocks.
- **Bibliographic metadata** (title, authors, journal, year, DOI) was completed from OpenAlex. The `metadata_basis`
  column records where each field came from.

**Sentences.** They were segmented and parsed with spaCy [@spaCy]:
- MME uses the scientific model `en_core_sci_sm` (scispaCy [@Neumann2019]) when installed, else `en_core_web_sm`,
  else a rule-based splitter.
- The model used is recorded for each paper (`extracted_with`), because it affects which values are linked to which
  material.

---

## 2.5 Quantity and unit extraction

**Patterns.** Quantities were found by patterns combining:
- a property term (for example "activation energy", "E_a", "σ_bulk", "diffusion coefficient");
- a number, possibly with uncertainty or a power of ten;
- a unit.

Publisher-specific glyph substitutions were repaired before matching: for example a lost multiplication sign, or
"Ω⁻¹ cm⁻¹" encoded in a symbol font.

**Units.** Values were converted to one unit per property:

| Property | Units recognised | Stored in |
|---|---|---|
| Activation energy | eV, meV, kJ mol⁻¹, kcal mol⁻¹ | eV |
| Ionic / electronic conductivity | S cm⁻¹, mS cm⁻¹, µS cm⁻¹, S m⁻¹, mS m⁻¹, µS m⁻¹, Ω⁻¹ cm⁻¹, (Ω cm)⁻¹, mho cm⁻¹ | S cm⁻¹ |
| Diffusion coefficient | cm² s⁻¹, m² s⁻¹ | cm² s⁻¹ |

**Kept with each value:**
- the value as printed (`raw_value`, `reported_as`);
- where it was read: text, table or caption (`extracted_from`), and its page, section and sentence.

**Numbers that are not results were discarded:** the spread of a distribution, a discrepancy between two values, or
a number inside a citation.

---

## 2.6 Material identification and linking

**Formulas.** Chemical formulas were parsed into element amounts, including:
- fractional and decimal subscripts;
- bracketed groups;
- hydrates;
- mixtures such as `70Li2S–30P2S5` and `(100−x)(0.75Li2S·0.25P2S5)·xLiBH4`.

**Composition series.** A series written with a variable (`Li7−3xFexLa3Zr2O12`, `Li6+xP1−xGexS5I`) was resolved to
one compound whenever x is fixed by any of the following:
- the value's own sentence or the one before;
- the paper's label of the series;
- a pairing of several values with several x ("respectively");
- a table column of x values.

Otherwise the series was kept as written and never reduced to an arbitrary member.

**Names.** Abbreviations defined by the paper ("Li3YCl6 (LYC)") and a curated list of common names (LLZO, LATP,
LGPS, …) were mapped to formulas.

**Doped samples.** A sample named after its parent with element symbols before it is recorded as its own material,
with the parent's composition: "Ta-LLZO", "Ga–LLZO", "Al,Ga-LLZO", "Ta-doped LLZO" and "Al-substituted
Li7La3Zr2O12" become "Ta-doped Li7La3Zr2O12" (the dopant's share is not stated). A single capital letter counts as a
dopant only together with the word "doped", because a single capital is often a processing tag ("S-LLZO",
sintered).

**Roles that are never the sample.** A material named in such a role takes no value:
- an electrode of a cell;
- a reagent;
- a filler;
- the salt of a polymer electrolyte.

**Linking a value to its material.** Each value was linked to one material by the first rule that applied
(`material_link`), with its confidence adjusted as shown:

| Rule | Where the material comes from | Confidence |
|---|---|---|
| `table_row` | the formula column, or x value, of the value's table row | 0.95 |
| `dependency_parse` / `proximity` | the same sentence: the material nearest to the value in the dependency tree, else in characters | context score + 0.1 |
| `table_caption` | the table's caption | 0.75 |
| `previous_sentence` / `paragraph_topic` | the sentence before, or the paragraph's topic material (running text only) | context score − 0.1 |

Values whose material could not be determined were stored without one (`unassigned_values.csv`).

---

## 2.7 Context of each value

For each value, MME recorded the following fields, together with a `basis` column stating, field by field, whether
each was stated in the paper or assumed, and why. The `n_assumed` column counts the assumed fields.

- **Transport component:** bulk, grain boundary, total or surface. Taken from the paper's words and from table
  headers (E_a,bulk, σ_gb, σ_tot). When none is stated it is assumed: total for a conductivity.
- **Origin:** measured (experimental) or computed (simulation). Decided from the sentence (method words such as
  impedance, NMR, DFT, AIMD, NEB) and, failing that, from the dominant kind of study of the paper.
- **Attribution:** the paper's own result ("this work"), or a value it cites. A value is cited when it carries a
  reference marker or appears with words of earlier work ("previously reported", "previous AIMD"). In a review
  paper every value is cited.
- **Mobile ion:** Li⁺, Na⁺, K⁺, Mg²⁺, Ca²⁺, Zn²⁺, Al³⁺, Ag⁺, Cu⁺, H⁺, F⁻, O²⁻, Cs⁺, Rb⁺ …, as stated. Otherwise it
  is the only conducting-ion element of the formula, else the ion the paper is about.
- **Kind of activation energy:**
  - an Arrhenius slope of measured transport (`arrhenius`);
  - a static migration barrier (`migration_barrier`, NEB);
  - a bond-valence barrier (`bvse`);
  - local hopping seen by NMR relaxation (`local_hop`);
  - a Vogel–Tammann–Fulcher pseudo-activation energy (`vtf`);
  - an energy of something other than ion migration: charge transfer, reaction or rotation (flagged).
- **Temperature and pressure.** "Room temperature" counts as 298.15 K only where needed and is marked as assumed.
  Pressure is ambient unless stated.
- **Structure:** a structure type stated next to the material ("cubic", "β-") or known for the composition.

---

## 2.8 Quality control

**Plausibility.** Values outside the range known for ion conductors were flagged (`plausibility = check: …`), not
removed:

| Property | Range |
|---|---|
| E_a | 0.05–1.5 eV |
| σ (ionic) | 10⁻¹²–10⁻¹ S cm⁻¹ |
| σₑ (electronic) | 10⁻¹⁴–10⁴ S cm⁻¹ |
| D | 10⁻¹⁶–10⁻³ cm² s⁻¹ |

Also flagged:
- values carried by a species that is no conducting ion;
- activation energies of processes other than ion migration.

**Scope.** Values of materials outside the database's domain were flagged and left out of the ranking. In an
electrolyte database these are:
- electrode compounds: transition-metal-rich, layered, spinel and olivine;
- metals and alloys;
- lithiated carbon;
- simple salts and interphase compounds;
- molecules;
- composites with polymers, gels or frameworks.

Cathode and anode databases flag solid electrolytes conversely.

**Arrhenius cross-check.** For each activation energy, the same paper's conductivities of the same material (and the
same component, when both state it) were gathered. When they covered at least two temperatures 20 K or more apart,
both common forms were fitted:

$$ \ln(\sigma T) = \ln A - \frac{E_a}{k_B T}, \qquad \ln \sigma = \ln A' - \frac{E_a}{k_B T}. $$

The reported value was *consistent* when either fit lay within 0.05 eV or 20 % of it, and *inconsistent* otherwise.

**Confidence score.** Each value received a heuristic score in [0.01, 0.99]:
- **Base:** 0.5.
- **Source:** +0.35 when read from a table, +0.25 from a caption.
- **Section:** +0.2 in the Results, Abstract or Conclusion; −0.1 in Supplementary text; −0.3 in boilerplate; 0 for
  a value in the reference list.
- **Cue words:** +0.15 for positive cue words; −0.35 for negative ones (hypothetical, literature).
- **Link:** adjusted by the linking rule of §2.6.

The score is not a probability. Its calibration was measured (§2.10).

**Values to check by a person.** The `needs_check` column flags, with the reasons:
- out of range;
- an unusual formula, one that does not balance in charge under common oxidation states;
- a doped sample stored under its parent formula;
- a material taken from another sentence;
- table text read as running text;
- confidence below 0.4.

**Duplicates.** Rows were matched as one measurement when all of the following agreed:
- material (by composition);
- property, component, origin and kind of energy;
- value: within 1 % or 0.002 eV for energies, within a factor of 1.02 for conductivities and diffusion coefficients;
- temperature: within 10 K.

A value repeated in its own paper, or quoted by a later paper, was traced to its original
(`measurement_id`, `original_paper`, `n_papers_reporting`). Two papers reporting the same value as their own were
marked as possible duplicates, never merged.

**Verification by hand.** Values could be marked correct, wrong or corrected in a verification interface showing
their sentence and page. The marks are stored apart from the database and applied in every export.

---

## 2.9 Aggregation

**Ranking.**
- **Components never mixed.** Each transport component (bulk, grain boundary, total) was ranked separately.
- **One energy per material.** Each material received one activation energy per component: by default the
  confidence-weighted median of its values, that is, the value at which half the total confidence is reached (the
  mean of the two middle values at an exact tie). Alternative policies: the lowest or the highest value.
- **Filters:** origin, attribution, kind of energy, mobile ion, element and minimum confidence. Values flagged as
  out of scope or of another process were excluded.
- **Evidence tier** of each material: A for three values or more from two papers or more; B for two values or more;
  C for a single value.
- **Rank intervals:** 1,000 bootstrap resamplings of each material's values (seed 20261116).

Electrolytes were classed by E_a:

| Class | E_a |
|---|---|
| superionic | < 0.25 eV |
| performant | 0.25–0.30 eV |
| acceptable | 0.30–0.40 eV |
| rejected | ≥ 0.40 eV |

Electrodes were classed by barrier: low (< 0.30 eV), moderate (0.30–0.50 eV) and high (> 0.50 eV).

**Classification.** Each material was assigned:
- **a crystal-structure type** (NASICON, LISICON, thio-LISICON, garnet, argyrodite, LGPS, perovskite,
  antiperovskite, spinel, olivine, layered, …): from structure words in the paper and from the composition (the
  stoichiometric pattern of mobile cations, framework cations and anions, a dopant-level share aside);
- **a structure family** (oxide, sulfide, halide, oxyhalide, nitride, hydride, …): from its anions.

Each class was further split by property, component and origin into datasets.

**Machine-learning datasets.** A dataset is one family, property, component and origin. Each gives:
- one row per material: median, log₁₀ for conductivities and diffusion coefficients, spread, numbers of values and
  papers, and a group key for grouped cross-validation;
- every contributing value, with its sentence and page;
- every value excluded, and why.

Repeated measurements were counted once, and values marked wrong by hand were excluded.

---

## 2.10 Evaluation

**Gold standard.**
1. **The draw.** **[run]** papers were drawn at random from the final databases, after the extraction rules had been
   frozen; the protocol was written before the draw (`docs/EVALUATION_PROTOCOL.md`).
2. **The annotation.** Two annotators, independently, judged every extracted value as correct, partly correct or
   wrong, and recorded every value the program missed, following a written guide.
3. **A value is correct** only when all of the following are right:
   - the number;
   - the material, where a doped sample stored as its parent is wrong;
   - the component, origin and attribution;
   - the kind of energy;
   - the domain.

**Agreement.** Inter-annotator agreement was measured with Cohen's κ. Disagreements were resolved by discussion
before scoring.

**Metrics.** For each property and overall, at two levels:
- **Value level:** the right number.
- **Value-and-material level:** the right number for the right material.

Precision, recall and F₁ are computed as

$$ P = \frac{TP}{TP+FP}, \qquad R = \frac{TP}{TP+FN}, \qquad F_1 = \frac{2PR}{P+R}. $$

- **Matching tolerances:** 1 % or 0.002 eV for energies; a factor of 1.02 (0.0086 in log₁₀) for conductivities and
  diffusion coefficients.
- **Intervals:** 95 % confidence intervals from 2,000 bootstrap resamplings of papers (the unit of sampling).
- **Calibration** of the confidence score: expected calibration error over five bins and the Brier score.
- **Also reported:** precision by source (text, table, caption) and an analysis of error types.

**Recall against curated databases.** The ionic conductivities of OBELiX [@Therrien2026] and the Liverpool Ionics
Dataset [@Hargreaves2023] were looked for among the values MME extracted from the same papers (legal open copies
only). Three levels were reported:
- material found;
- material and value within 0.1 decade;
- material and value within 2 %.

Entries reported only in figures were counted separately.

**Benchmark.** On the same annotated papers and with the same tolerances, MME was compared with:
- a keyword baseline: a number with the property's unit in a sentence naming the property;
- ChemDataExtractor [@Swain2016];
- **[run: an LLM-based extractor, model and prompt given in the SI]**.

Paired differences in F₁ with MME were computed on the same bootstrap resamples.

**Earlier audit.** Precision was also estimated in an independent audit of two rounds of 40 random papers, using the
same definition of a correct value, with 95 % Wilson intervals.

---

## 2.11 Reproducibility and data availability

- **Software.** MoukhlijMatExtract **[version]** (AGPL-3.0-or-later), **[release DOI]**. Python 3.11–3.13, tested
  on Linux, Windows and macOS by continuous integration on every change (about 950 tests).
- **Environment.** Exact package versions in `requirements.lock`; a Docker image pins the same environment with
  Tesseract.
- **Run records.** Every stage appends a manifest (`run_manifest.json`) to its output. It records:
  - the command and settings;
  - the software version and git commit;
  - the language model, Tesseract, Python and package versions;
  - the counts;
  - the SHA-256 checksum of every file written.
- **Regeneration.** `make paper` regenerates every table and figure of this article from the released data, with
  fixed random seeds.
- **Data.** The database, the ranking, the classification, the data dictionary and the manifests are deposited at
  Zenodo (**[DOI]**). Text quoted from papers is included only where the paper's licence permits redistribution
  (CC BY, CC0, public domain). The provenance (DOI, page, table, row) of every value is always included.
- **Gold standard.** The annotated papers are released separately under CC BY 4.0 (**[DOI]**).

---

### What to fill in before submission

| Where | From |
|---|---|
| Corpus counts (§2.2), Table S of publishers | `mme-web coverage` |
| Database counts | `make paper` → `tables/database_summary.csv` |
| Gold-standard size, κ, P/R/F₁ (§2.10) | `mme-eval agree`, `mme-eval score` |
| Benchmark | `mme-eval benchmark --tool …` |
| Version and DOIs | the GitHub release and Zenodo |

References use the keys of `paper/paper.bib`.
