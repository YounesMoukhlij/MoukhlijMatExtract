# MoukhlijMatExtract — command reference

Every command of the project with all of its options, as each prints them with `--help`.
Written by `mme commands --markdown --output docs/COMMANDS.md` (or `make commands`): do not edit it by
hand. How to use the commands, in order, and how to reproduce a result: [MANUAL.md](MANUAL.md).

| Command | Same as | make | What it does |
|---|---|---|---|
| [`mme`](#mme) | `python -m mme_gui.commands` | `make help` | every command in one: mme help, mme commands, mme <part> … |
| [`mme-gui`](#mme-gui) | `python -m mme_gui` | `make gui` | opens the main window: one button per part |
| [`mme-local`](#mme-local) | `python -m LocalExtraction extract` | `make local` | reads your PDFs into a database |
| [`mme-local gui`](#mme-local-gui) | `python -m LocalExtraction gui` | `make local-gui` | the same, in its window |
| [`mme-dois`](#mme-dois) | `python -m WebScraping.Fetch_DOIs.get_dois` | `make doi` | 1 · Fetch DOIs: collects the DOIs of the topic |
| [`mme-web`](#mme-web) | `python -m WebScraping run` | `make web` | search, review, download and extract |
| [`mme-web gui`](#mme-web-gui) | `python -m WebScraping gui` | `make web-gui` | the same, in its window |
| [`mme-rank`](#mme-rank) | `python -m SelectingTopMaterial` | `make rank` | ranks the materials by activation energy |
| [`mme-rank gui`](#mme-rank-gui) | `python -m SelectingTopMaterial gui` | `make rank-gui` | the same, in its window |
| [`mme-classify`](#mme-classify) | `python -m Classification` | `make classify` | sorts the materials by crystal and structure family |
| [`mme-classify gui`](#mme-classify-gui) | `python -m Classification gui` | `make classify-gui` | the same, in its window |
| [`mme-eval sheet`](#mme-eval-sheet) | `python -m Evaluation sheet` | `make eval-sheet` | draws papers, writes the workbook to annotate |
| [`mme-eval score`](#mme-eval-score) | `python -m Evaluation score` | `make eval-score` | precision, recall, F1 against the annotations |
| [`mme-eval agree`](#mme-eval-agree) | `python -m Evaluation agree` | `make eval-agree` | agreement of two annotators |
| [`mme-eval reference`](#mme-eval-reference) | `python -m Evaluation reference` | `make eval-reference` | recall against curated databases (OBELiX, Liverpool) |
| [`mme-release`](#mme-release) | `python -m Release` | `make release` | the dataset, ready to deposit (Zenodo) |

## mme

*Every command* — every command in one: mme help, mme commands, mme <part> …. Same as `python -m mme_gui.commands`; with make: `make help`.

```text
usage: mme [-h] [--version] {help,commands,gui,local,web,dois,rank,classify,eval,release} ...

Every command of MoukhlijMatExtract in one. `mme <part> …` runs a part (gui, local, web, dois,
rank, classify, eval, release): mme local, mme web run, mme rank --domain cathode …

positional arguments:
  {help,commands,gui,local,web,dois,rank,classify,eval,release}
    help                Every command at a glance, with the typical runs
    commands            Every command with all of its options
    gui                 Runs mme_gui (mme-gui); add --help for its options
    local               Runs LocalExtraction (mme-local); add --help for its options
    web                 Runs WebScraping (mme-web); add --help for its options
    dois                Runs WebScraping.Fetch_DOIs.get_dois (mme-dois); add --help for its
                        options
    rank                Runs SelectingTopMaterial (mme-rank); add --help for its options
    classify            Runs Classification (mme-classify); add --help for its options
    eval                Runs Evaluation (mme-eval); add --help for its options
    release             Runs Release (mme-release); add --help for its options

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
```

## mme-gui

*The one window* — opens the main window: one button per part. Same as `python -m mme_gui`; with make: `make gui`.

```text
usage: mme-gui [-h] [--version]

Open the MoukhlijMatExtract window: one button per part.

options:
  -h, --help  show this help message and exit
  --version   show program's version number and exit
```

## mme-local

*1 · Local extraction* — reads your PDFs into a database. Same as `python -m LocalExtraction extract`; with make: `make local`.

```text
usage: mme-local extract [-h] [--input INPUT] [--output OUTPUT] [--workers WORKERS] [--verbose]
                         [--domain {electrolyte,cathode,anode}] [--offline] [--rebuild]

options:
  -h, --help            show this help message and exit
  --input, -i INPUT     Directory containing input PDFs, relative to
                        ~/MoukhlijMatExtract (default: LocalExtraction/papers)
  --output, -o OUTPUT   Directory to write the extracted database into, relative to
                        ~/MoukhlijMatExtract (default:
                        LocalExtraction/local_output)
  --workers, -w WORKERS
                        Number of PDFs to process in parallel (default: 4)
  --verbose, -v         Enable debug-level logging
  --domain {electrolyte,cathode,anode}
                        What the papers are about (default: electrolyte): values of a material of
                        another kind are flagged, and the ranking leaves them out. Keep one output
                        folder per domain
  --offline             Do not complete the papers' title, authors, journal, DOI, year and license
                        from OpenAlex
  --rebuild             Extract every PDF again instead of only the new ones. The present database
                        files are not deleted: they are moved to <output>/previous_<date>/
```

## mme-local gui

*1 · Local extraction* — the same, in its window. Same as `python -m LocalExtraction gui`; with make: `make local-gui`.

```text
usage: mme-local gui [-h] [--input INPUT] [--output OUTPUT] [--workers WORKERS] [--verbose]
                     [--domain {electrolyte,cathode,anode}] [--offline]

options:
  -h, --help            show this help message and exit
  --input, -i INPUT     Directory containing input PDFs, relative to
                        ~/MoukhlijMatExtract (default: LocalExtraction/papers)
  --output, -o OUTPUT   Directory to write the extracted database into, relative to
                        ~/MoukhlijMatExtract (default:
                        LocalExtraction/local_output)
  --workers, -w WORKERS
                        Number of PDFs to process in parallel (default: 4)
  --verbose, -v         Enable debug-level logging
  --domain {electrolyte,cathode,anode}
                        What the papers are about (default: electrolyte): values of a material of
                        another kind are flagged, and the ranking leaves them out. Keep one output
                        folder per domain
  --offline             Do not complete the papers' title, authors, journal, DOI, year and license
                        from OpenAlex
```

## mme-dois

*2 · Web scraping* — 1 · Fetch DOIs: collects the DOIs of the topic. Same as `python -m WebScraping.Fetch_DOIs.get_dois`; with make: `make doi`.

```text
usage: mme-dois [-h] [--version] [--count N] [--job JOB] [--max MAX] [--out OUT] [--refresh]
                [--no-expand]
                [keywords ...]

Collect DOIs for keywords into a CSV file (and the bare DOIs into a text file next to it). Each
run adds to the list.

positional arguments:
  keywords       e.g. "solid electrolyte" "LLZO garnet" (default: the queries of the job file)

options:
  -h, --help     show this help message and exit
  --version      show program's version number and exit
  --count, -n N  how many NEW DOIs to add to the list (1 or more), then stop. Without it there is
                 no limit: the search goes on until you stop it (Ctrl-C); what was found is kept
  --job JOB      job file whose queries, years, sources and max_per_query are used (default:
                 configs/sse.yaml)
  --max MAX      results asked from each source per keyword (default: the job's max_per_query,
                 else 100)
  --out OUT      CSV file (default: WebScraping/Fetch_DOIs/dois.csv)
  --refresh      ask the sources again the keywords they already answered (by default a keyword a
                 source answered in the last 30 days is skipped)
  --no-expand    use only the keywords given: do not go on with keywords made of topic and
                 property words when they run dry
```

## mme-web

*2 · Web scraping* — search, review, download and extract. Same as `python -m WebScraping run`; with make: `make web`.

```text
usage: mme-web run [-h] [--job JOB] [--output OUTPUT] [--workers WORKERS] [--verbose]
                   [--stage {discover,fetch,extract}] [--yes] [--limit LIMIT] [--dois [FILE]]
                   [--check] [--probe-doi PROBE_DOI] [--refresh] [--rebuild]

options:
  -h, --help            show this help message and exit
  --job JOB             Job file (YAML): what to search for, which papers to keep, what to extract
                        (default: configs/sse.yaml)
  --output, -o OUTPUT   Directory to write the extracted database into (default:
                        WebScraping/web_output)
  --workers, -w WORKERS
                        Number of PDFs to process in parallel (default: 4)
  --verbose, -v         Enable debug-level logging
  --stage {discover,fetch,extract}
                        First stage to run. discover (default): search and screen, then stop for
                        your review if the job asks for one. fetch: after the review, fetch what
                        you approved and extract it. extract: only extract what is already fetched
  --yes                 Approve every proposed paper without a review
  --limit LIMIT         Fetch at most this many papers in this run
  --dois [FILE]         Search with DOIs: take in the DOIs of a list (default: the list of mme-
                        dois, WebScraping/Fetch_DOIs/dois.csv), check them like the keyword
                        results (OpenAlex record, abstract, topic score), then fetch the legal
                        open-access copies of those on topic and extract them — no keyword search.
                        (A plain run takes the job's doi_list in too.)
  --check               Test the setup (network, API keys, folders) and exit
  --probe-doi PROBE_DOI
                        With --check: an Elsevier DOI to test the Elsevier API key with
  --refresh             Search again the queries already searched (by default a query a source
                        answered in the last 30 days is skipped)
  --rebuild             Extract every fetched PDF again instead of only the new ones. The present
                        database files are not deleted: they are moved to
                        <output>/previous_<date>/
```

## mme-web gui

*2 · Web scraping* — the same, in its window. Same as `python -m WebScraping gui`; with make: `make web-gui`.

```text
usage: mme-web gui [-h] [--job JOB] [--output OUTPUT] [--workers WORKERS] [--verbose]

options:
  -h, --help            show this help message and exit
  --job JOB             Job file (YAML): what to search for, which papers to keep, what to extract
                        (default: configs/sse.yaml)
  --output, -o OUTPUT   Directory to write the extracted database into (default:
                        WebScraping/web_output)
  --workers, -w WORKERS
                        Number of PDFs to process in parallel (default: 4)
  --verbose, -v         Enable debug-level logging
```

## mme-rank

*3 · Ranking* — ranks the materials by activation energy. Same as `python -m SelectingTopMaterial`; with make: `make rank`.

```text
usage: mme-rank [-h] [--source DIR [DIR ...]] [--out DIR] [--criteria FILE]
                [--domain {electrolyte,cathode,anode}]
                [--policy {consensus,optimistic,conservative}] [--by-phase]
                [--origin {experimental,simulation}] [--attribution {this-work,cited}]
                [--component NAME]
                [--kind {arrhenius,migration_barrier,bvse,local_hop,vtf,unspecified}]
                [--element SYMBOL [SYMBOL ...]] [--min-confidence 0-1] [--include-flagged]
                [--top N] [--format FORMAT [FORMAT ...]] [--no-files] [--open] [--quiet]
                [--no-color] [--force] [--version]

Ranks the materials of the MoukhlijMatExtract database by activation energy and sorts them into
the classes of criteria.toml (Superionic, Performant, Acceptable, Rejected) — one ranking per
transport component: bulk, grain boundary and total.

options:
  -h, --help            show this help message and exit
  --source, -s DIR [DIR ...]
                        Results folder(s) to read, the most trusted first (default:
                        LocalExtraction/local_output and WebScraping/web_output, whichever exist)
  --out, -o DIR         Folder to write the ranking into (default: SelectingTopMaterial/results)
  --criteria FILE       Criteria file to use instead of SelectingTopMaterial/criteria.toml
  --domain {electrolyte,cathode,anode}
                        What the materials are: electrolyte (criteria.toml), cathode
                        (criteria_cathode.toml) or anode (criteria_anode.toml), unless --criteria
                        names a file (default: electrolyte)
  --policy {consensus,optimistic,conservative}
                        Which activation energy stands for a material that has several: consensus
                        = confidence-weighted median of the material's values; optimistic = lowest
                        value reported for the material; conservative = highest value reported for
                        the material (default: the one of the criteria file)
  --by-phase            Rank the phases of a composition apart (cubic / tetragonal, β / γ) when
                        the database names them
  --force, -f           Rank again even when nothing has changed since the last ranking written
  --version             show program's version number and exit

which values take part:
  --origin {experimental,simulation}
                        Only measured values, or only computed ones
  --attribution {this-work,cited}
                        Only the papers' own results, or only the values they cite
  --component NAME      Rank one transport component only: bulk, grain_boundary (or "grain
                        boundary"), total. By default each is ranked on its own, into a folder of
                        its own
  --kind {arrhenius,migration_barrier,bvse,local_hop,vtf,unspecified}
                        Rank one kind of energy only (the energy_kind column): arrhenius (the
                        slope of long-range transport: impedance, molecular dynamics),
                        migration_barrier (a static barrier of one hop, NEB), bvse, local_hop (NMR
                        relaxation), vtf. Different kinds are different quantities; by default all
                        take part
  --element SYMBOL [SYMBOL ...]
                        Only the materials that contain these elements (--element Na: the sodium
                        conductors)
  --min-confidence 0-1  Only the values the extraction gave at least this confidence (default:
                        all)
  --include-flagged     Also rank the values the extraction flagged (plausibility "check: …"):
                        outside 0.05–1.5 eV, or the transport of electrons or of another element
                        than a conducting ion. By default they are left out

what is shown and written:
  --top N               Keep the first N materials that pass, in the terminal and in top_materials
  --format FORMAT [FORMAT ...]
                        Files to write: csv, xlsx, json, html (default: all of them)
  --no-files            Show the ranking, write nothing
  --open                Open the report in the browser once written
  --quiet, -q           Say nothing but what goes wrong
  --no-color            No colours in the terminal

The database is only read. Each component's ranking is written into a folder of its own —
SelectingTopMaterial/results/bulk/, grain_boundary/, total/ — with summary.csv beside them. The
window: mme-rank gui (mme-rank gui --help for its options). MoukhlijMatExtract (MME) — Created by
Younes Moukhlij.
```

## mme-rank gui

*3 · Ranking* — the same, in its window. Same as `python -m SelectingTopMaterial gui`; with make: `make rank-gui`.

```text
usage: mme-rank gui [-h] [--source DIR [DIR ...]] [--out DIR] [--criteria FILE]

The window of the selection.

options:
  -h, --help            show this help message and exit
  --source, -s DIR [DIR ...]
                        Results folder(s) to offer, the most trusted first (default:
                        LocalExtraction/local_output, WebScraping/web_output)
  --out, -o DIR         Folder to write the ranking into (default: SelectingTopMaterial/results)
  --criteria FILE       Criteria file to use instead of criteria.toml
```

## mme-classify

*4 · Classification* — sorts the materials by crystal and structure family. Same as `python -m Classification`; with make: `make classify`.

```text
usage: mme-classify [-h] [--version] [--source DIR [DIR ...]] [--out DIR] [--force]

Classifies the materials of the MoukhlijMatExtract databases by crystal-structure type (NASICON,
LISICON, garnet, ...) and by structure family (oxide, sulfide, halide, ...), and writes one
database per class.

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --source, -s DIR [DIR ...]
                        Database folder(s) to read, the most trusted first (default:
                        LocalExtraction/local_output and WebScraping/web_output, whichever exist)
  --out, -o DIR         Folder to write the classes into (default: Classification/)
  --force, -f           Classify again even when the databases have not changed since the last run

The window: mme-classify gui. MoukhlijMatExtract (MME) — Created by Younes Moukhlij.
```

## mme-classify gui

*4 · Classification* — the same, in its window. Same as `python -m Classification gui`; with make: `make classify-gui`.

```text
usage: mme-classify gui [-h] [--source DIR [DIR ...]] [--out DIR] [--no-write]

The window of the classification.

options:
  -h, --help            show this help message and exit
  --source, -s DIR [DIR ...]
                        Database folder(s) to classify (default: LocalExtraction/local_output and
                        WebScraping/web_output)
  --out, -o DIR         Folder the class folders are written into (default: Classification/)
  --no-write            Only show the classes; write no file

MoukhlijMatExtract (MME) — Created by Younes Moukhlij.
```

## mme-eval sheet

*Evaluation* — draws papers, writes the workbook to annotate. Same as `python -m Evaluation sheet`; with make: `make eval-sheet`.

```text
usage: mme-eval sheet [-h] [--source DIR [DIR ...]] [--papers N] [--seed SEED] [--out FILE]
                      [--force] [--all-papers]

Draws papers at random from the databases — with and without extracted values, so recall is
measured honestly — and writes a workbook with every value extracted from them, to mark correct /
partly / wrong, and a sheet for the values missed. The same databases and seed give the same
papers.

options:
  -h, --help            show this help message and exit
  --source, -s DIR [DIR ...]
                        Results folder(s) to draw from, the most trusted first (default:
                        LocalExtraction/local_output and WebScraping/web_output, whichever exist)
  --papers, -n N        How many papers to draw (default: 60; 50–100 is usual for a publication)
  --seed SEED           Seed of the random draw (default: 7)
  --out, -o FILE        Workbook to write (default: Evaluation/annotation.xlsx)
  --force               Replace an existing workbook; the old one is kept as <name>.<date>.xlsx
  --all-papers          Draw from every paper. By default only the papers mme-release would
                        publish are drawn (a legal copy recorded, or the authors' own PDFs), so
                        the scores describe the dataset you deposit

Typical use: mme-eval sheet → annotate Evaluation/annotation.xlsx (its Guide sheet says how) →
mme-eval score. After changing the program and extracting again: mme-eval score --source
LocalExtraction/local_output WebScraping/web_output, to measure the new version against the same
reference. MoukhlijMatExtract (MME) — Created by Younes Moukhlij.
```

## mme-eval score

*Evaluation* — precision, recall, F1 against the annotations. Same as `python -m Evaluation score`; with make: `make eval-score`.

```text
usage: mme-eval score [-h] [--gold FILE] [--source DIR [DIR ...]] [--out DIR] [--seed SEED]
                      [--predictions CSV [CSV ...]]

Precision, recall and F1 per property and overall, at the value level (right number) and the
record level (right number and material), with 95 % bootstrap intervals; the accuracy of the
component and origin; the calibration of the confidence column; the errors. Only the papers marked
done are scored.

options:
  -h, --help            show this help message and exit
  --gold, -g FILE       The annotated workbook (default: Evaluation/annotation.xlsx)
  --source, -s DIR [DIR ...]
                        Score the values now in these results folders (a newer run) instead of
                        those the workbook was made from
  --out, -o DIR         Folder of the report (default: Evaluation/scores)
  --seed SEED           Seed of the bootstrap (default: 7)
  --predictions, -p CSV [CSV ...]
                        Other tools' values for the same papers (ChemDataExtractor, …), each a CSV
                        with paper_id, property, material, value [, unit, component, origin,
                        confidence]: scored the same way and compared with MoukhlijMatExtract
                        (comparison.md, paired bootstrap)

Typical use: mme-eval sheet → annotate Evaluation/annotation.xlsx (its Guide sheet says how) →
mme-eval score. After changing the program and extracting again: mme-eval score --source
LocalExtraction/local_output WebScraping/web_output, to measure the new version against the same
reference. MoukhlijMatExtract (MME) — Created by Younes Moukhlij.
```

## mme-eval agree

*Evaluation* — agreement of two annotators. Same as `python -m Evaluation agree`; with make: `make eval-agree`.

```text
usage: mme-eval agree [-h] first second

On the papers both marked done: Cohen's kappa of the verdicts, the raw agreement, and the F1 of
one reference set against the other.

positional arguments:
  first       The workbook of the first annotator
  second      The workbook of the second annotator

options:
  -h, --help  show this help message and exit

Typical use: mme-eval sheet → annotate Evaluation/annotation.xlsx (its Guide sheet says how) →
mme-eval score. After changing the program and extracting again: mme-eval score --source
LocalExtraction/local_output WebScraping/web_output, to measure the new version against the same
reference. MoukhlijMatExtract (MME) — Created by Younes Moukhlij.
```

## mme-eval reference

*Evaluation* — recall against curated databases (OBELiX, Liverpool). Same as `python -m Evaluation reference`; with make: `make eval-reference`.

```text
usage: mme-eval reference [-h] [--db {liverpool,obelix} [{liverpool,obelix} ...]] [--no-fetch]
                          [--limit N] [--refresh] [--workers WORKERS]
                          [--predictions CSV [CSV ...]]

Downloads curated databases of solid electrolytes, fetches the legal open copies of their papers
into Evaluation/reference/papers/ (apart from your databases), extracts them into
Evaluation/reference/output/, and finds each curated entry among the extracted ionic
conductivities: same composition, same value (0.1 decade; 2 %), compatible temperature. Each step
is skipped when already done; PDFs you add by hand to the papers folder are read too.

options:
  -h, --help            show this help message and exit
  --db {liverpool,obelix} [{liverpool,obelix} ...]
                        Which databases (default: all)
  --no-fetch            Do not look for more papers; compare what is there
  --limit N             Look for at most N more papers in this run
  --refresh             Download the curated databases again
  --workers, -w WORKERS
                        PDFs extracted in parallel (default: 4)
  --predictions CSV [CSV ...]
                        Other tools' values for the same PDFs (Evaluation/reference/papers/),
                        scored the same way, side by side in the report (columns paper_id,
                        property, material, value, unit)

Typical use: mme-eval sheet → annotate Evaluation/annotation.xlsx (its Guide sheet says how) →
mme-eval score. After changing the program and extracting again: mme-eval score --source
LocalExtraction/local_output WebScraping/web_output, to measure the new version against the same
reference. MoukhlijMatExtract (MME) — Created by Younes Moukhlij.
```

## mme-release

*Release* — the dataset, ready to deposit (Zenodo). Same as `python -m Release`; with make: `make release`.

```text
usage: mme-release [-h] [--source DIR [DIR ...]] [--with DIR [DIR ...]] [--no-results] [--out DIR]
                   [--keep-text] [--keep-unrecorded] [--finish FOLDER] [--version]

Gathers the databases, the ranking and the classification into one folder and one .zip, ready to
deposit (Zenodo, Figshare, a journal): every value and bibliographic field; the text copied from a
paper only where its license lets anyone share it (CC BY, CC0, public domain); the data
dictionary, the run manifests, requirements.lock, a datasheet (README.md, with the parts only you
can write marked TO COMPLETE) and SHA256SUMS.

options:
  -h, --help            show this help message and exit
  --source, -s DIR [DIR ...]
                        Database folder(s) to release (default: LocalExtraction/local_output and
                        WebScraping/web_output, whichever exist)
  --with DIR [DIR ...]  Other result folders to add (default: SelectingTopMaterial/results and
                        Classification, whichever exist)
  --no-results          Release the databases only
  --out, -o DIR         Folder the release is written into (default: Release/)
  --keep-text           Keep the text of every paper, whatever its license (for sharing with your
                        co-authors, not for a public deposit)
  --keep-unrecorded     Keep the papers with no record of a legal copy (a copy from a shadow
                        library, or a downloaded PDF whose source was not recorded) — for your own
                        use only, never a public deposit. By default they are left out, and listed
                        in excluded.csv
  --finish FOLDER       After completing the README of a release folder: write its SHA256SUMS and
                        .zip again
  --version             show program's version number and exit

Nothing of the databases is changed. MoukhlijMatExtract (MME) — Created by Younes Moukhlij.
```
