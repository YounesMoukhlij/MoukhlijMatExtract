---
title: 'MoukhlijMatExtract: legal, large-scale retrieval and traceable extraction of ion-transport data for battery materials'
tags:
  - Python
  - materials science
  - text mining
  - solid-state electrolytes
  - battery materials
  - activation energy
  - ionic conductivity
authors:
  - name: Younes Moukhlij
    orcid: 0009-0005-7348-7942
    affiliation: 1
affiliations:
  - name: Multidisciplinary Faculty of Khouribga (FPK), Sultan Moulay Slimane University (USMS), Morocco
    index: 1
date: 22 November 2026
bibliography: paper.bib
---

<!-- Before submission: update the corpus numbers of "Use at scale" from the latest `mme-web coverage` and the
     benchmark from `mme-eval benchmark` on the final gold standard; check the word count (JOSS: 250–1000 words). -->

# Summary

MoukhlijMatExtract (MME) builds databases of ion-transport properties from the scientific literature on battery
materials: solid-state electrolytes, cathodes and anodes. It searches 25 open bibliographic services and
OpenAlex's full-text index for the papers that report activation energies, ionic and electronic conductivities and
diffusion coefficients. It downloads only legally available copies (open access, publishers' text-and-data-mining
interfaces, institutional repositories) and extracts every value with its unit converted, its material resolved to
a composition, and its context: transport component (bulk, grain boundary, total), measured or computed, the paper's
own result or a cited one, the mobile ion, and the kind of energy (Arrhenius slope, migration barrier, local hop…).
Every value keeps its provenance: page, section, sentence, and table cell or caption. MME then ranks the materials
per transport component, classifies them by crystal-structure type and chemical family, exports datasets for
machine learning, measures its own accuracy, and packages a license-checked dataset for deposit. It runs as a
desktop application or as command-line tools on macOS, Linux and Windows.

# Statement of need

Screening solid electrolytes and electrodes depends on comparing ion-transport data across thousands of papers
[@Bachman2016; @Famprikis2019]. These data are scattered in prose, tables and captions, in many units and
conventions. Curated databases such as the Liverpool Ionics Dataset [@Hargreaves2023] and OBELiX [@Therrien2026]
are carefully checked, but each holds a few hundred materials and took sustained manual effort; they cannot keep
pace with the literature. Researchers who want a broader or more current corpus — a new chemical family, cathodes
or anodes, computed migration barriers — have no tool that covers the whole path from finding the papers to a
traceable, rankable dataset.

MME is built for materials scientists without a text-mining background, and for reviewers who must be able to
check any number. Its design choices follow from that audience:

- **Scale, legally.** Each job file targets a domain or family. Keyword searches, citation snowballing and
  full-text searches find the candidate papers; a transparent score proposes them; seventeen copy sources are tried
  in turn. Rate limits, `robots.txt` and refusals are respected, and no paywall or bot check is bypassed.
- **Traceability.** Every value can be traced to its sentence and table cell, and every assumption (for example a
  component inferred rather than stated) is recorded in a `basis` column. Each run writes a manifest with the
  software version, commit, language model and file checksums.
- **Measured quality.** `mme-eval` draws papers at random for annotation, scores precision and recall with
  bootstrap intervals, measures annotator agreement, compares MME with a keyword baseline and other tools on the
  same papers, measures recall against curated databases, and packages the annotations as a public gold standard.

# State of the field

ChemDataExtractor [@Swain2016] is the reference rule-based toolkit for chemical text mining; it was used to
auto-generate a battery-materials database of capacities, voltages, conductivities and Coulombic efficiencies
[@Huang2020]. Text-mining pipelines have also produced synthesis-recipe datasets [@Kononova2019]; the field is
reviewed by @Olivetti2020. Large language models now extract materials data with high accuracy from given texts
[@Polak2024; @Dagdelen2024]. MME differs in scope rather than in a single algorithm: it covers retrieval at scale
from legal sources, not only extraction from a supplied corpus; it records the transport component, the kind of
activation energy and whether a value is the paper's own, which ion-transport screening needs but general schemas
lack; it traces repeated and quoted values back to one measurement; and it is deterministic and runs offline at no
per-paper cost, so a published dataset can be regenerated exactly. MME scores any external tool's output on its
gold standard, so these approaches can be compared directly.

# Implementation

MME is written in Python. PDFs are read with PyMuPDF, scanned pages with Tesseract [@Smith2007], and sentences are
parsed with spaCy [@spaCy] or scispaCy [@Neumann2019]. Discovery uses OpenAlex [@Priem2022] and 24 further services;
compositions can be linked to Materials Project entries [@Jain2013]. The packages are: `LocalExtraction` (the
extraction engine), `WebScraping` (discovery, screening, legal download, resumable ledger), `SelectingTopMaterial`
(ranking), `Classification`, `MLDataset`, `Evaluation` and `Release`. A test suite of about 940 tests runs on every
push on Linux (Python 3.11–3.13), Windows and macOS; a pinned lock file and a Dockerfile reproduce the environment,
and `make paper` regenerates every table and figure of a study from its data.

# Use at scale and current limitations

On garnet and NASICON solid electrolytes, a single job screened 59,023 bibliographic records, proposed 2,446
papers, downloaded 918 legal copies and extracted 1,041 activation energies and 3,047 ionic conductivities from
930 papers. Full-text search adds the papers whose abstracts do not mention the property: in a test on garnets it
re-proposed 229 papers the abstract-based screening had turned down.

The number itself is read correctly for about 95 % of values, but assigning it to the right material is harder: in
an independent audit of activation energies, 37–41 % of values were correct in every attribute (number, material,
component, origin, kind of energy), and recall against curated databases is limited by values reported only in
figures. These measurements, and how to reproduce them, are documented with the software; the `needs_check`
column and a verification interface direct manual checking to the values that need it.

# Acknowledgements

The author thanks the open bibliographic infrastructures (OpenAlex, Crossref, arXiv, Europe PMC, CORE and others)
and the publishers who provide text-and-data-mining access.

# References
