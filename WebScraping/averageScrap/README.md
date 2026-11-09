# WebScraping — Part 2

A part of [MoukhlijMatExtract (MME)](../../README.md) · Author: Younes Moukhlij

Instead of collecting PDFs by hand, describe what you are looking for and let the program find the
papers, fetch the ones you can legally read, and extract from them with the pipeline of
[LocalExtraction](../../LocalExtraction/README.md).

| | |
|---|---|
| **Input** | the job file `configs/sse.yaml` (what to search for) and the web |
| **Output** | the PDFs in `WebScraping/papers/`, and the database `WebScraping/web_output/` — the same files as [LocalExtraction's](../../LocalExtraction/README.md#output) |
| **Read by** | [SelectingTopMaterial](../../SelectingTopMaterial/README.md) and [Crystal and Structure Classification](../../Classification/README.md) |

## Set up (once)

The whole project works inside one virtual environment (venv), `.venv/` in the project folder.
From the project folder (the one that holds `WebScraping/`), with Python 3.11 or newer:

```bash
python3 -m venv .venv                     # create the venv, once
source .venv/bin/activate                 # enter it (Windows: .venv\Scripts\activate)
pip install -r requirements.txt           # install the packages inside it
python -m spacy download en_core_web_sm   # and the language model
```

Then work inside it: enter it (`source .venv/bin/activate`) in every new terminal before you run
the commands below; your prompt then starts with `(.venv)`. The
[main README](../../README.md#installation) has the whole setup, Tesseract included.

## Run it

From the project folder, inside the venv:

```bash
python -m WebScraping                    # search, screen, download and extract — all of it
python -m WebScraping --check            # test the setup (network, keys, folders) first, if you like
python -m WebScraping gui                # the same steps in a window
```

One command runs every stage: it searches, keeps the papers whose title and abstract score
(`screen.min_score`), downloads them and extracts them into `WebScraping/web_output/`. To look at
the list before anything is downloaded, set `review: true` in the job file: the command then stops
after the search, you set `decision` in `WebScraping/papers/candidates.csv` (or in the window's
table), and `python -m WebScraping --stage fetch` goes on from there.

| Option | What it does |
|---|---|
| `--job FILE` | The job file: what to search for, which papers to keep, what to extract (default: `configs/sse.yaml`) |
| `--output DIR`, `-o` | Where the database goes (default: `WebScraping/web_output`) |
| `--stage discover\|fetch\|extract` | The first stage to run (default: `discover`, i.e. all of them) |
| `--limit N` | Fetch at most N papers in this run |
| `--yes` | Approve every proposal without a review, even with `review: true` |
| `--check` | Test the setup (network, API keys, folders) and exit |
| `--rebuild` | Extract every fetched PDF again; the present database files are moved to `<output>/previous_<date>/` (a database written by an earlier version is rebuilt so without being asked), and every paper of it comes back |
| `--workers N`, `-w` | PDFs read in parallel (default: 4) |

A run is resumable at every step (everything is recorded in `WebScraping/papers/ledger.sqlite`):
run the same command again after a crash, a Ctrl-C or a review and it carries on, never fetching a
paper twice. The same steps are buttons in [the window](#the-window), with the review done in a
table instead of a spreadsheet.

Your e-mail and keys (Elsevier, Wiley, CORE, Springer Nature, NASA ADS, ...), all optional and all
free, go in `WebScraping/averageScrap/.env` — or in **API keys…** in the window (one card per
organization), which writes that file. The file
already has an empty line for each one; a source whose key is empty is skipped, and `--check` says
where each key is had (see [Where papers are searched for](#where-papers-are-searched-for)).

## The window

- **`python -m WebScraping gui`** is `python -m WebScraping`, one button per stage. *Search* asks the
  sources and screens the hits. The **Candidates** table is the review: filter it, select rows and
  press ✓ Yes / ✗ No — or the keys y and n — (a double click shows the abstract and why the paper
  was proposed). It is the same list as `WebScraping/papers/candidates.csv` — a list reviewed in a
  spreadsheet shows up here, and what you decide here is what the terminal's fetch stage reads.
  *Download* fetches the papers marked yes, each line saying where the copy came from or why none
  was had; *Extract* reads the downloaded articles into its results folder (by default right
  after the download).
  - **API keys…** shows one card per organization — your contact e-mail, Elsevier, Wiley, OpenAlex,
    Semantic Scholar, CORE, Springer Nature, NASA ADS, IEEE Xplore, Web of Science, The Lens, Dimensions,
    BASE — each with what
    its key opens, whether it is set, and a **Get a free key ↗** button to its sign-up page. They are
    saved in `WebScraping/averageScrap/.env`, which git ignores.
  - **Search settings…** shows the job as a form — searches, years, sources, screening words, where
    copies are looked for, the properties to keep — each number within its bounds, and saves it as a
    job file the terminal reads too, keeping its comments and `# headings`. What may not change (the
    folder of the PDFs, the job's name) is shown, not offered; **Reset to defaults** puts back the
    shipped job. **Check setup** is `--check`.
  - **Pause** holds the running step (what is under way finishes first) and **Resume** goes on.
    When the internet goes, the step says *No internet connection — waiting for it to come back* and
    goes on by itself once it is back, instead of taking every paper of the outage for failed.

## How it works

```
python -m WebScraping
    │
    ▼
WebScraping/sources       — OpenAlex, arXiv, Crossref, Semantic Scholar, Europe PMC, OpenAIRE, DOAJ, J-STAGE,
                            CORE, Springer Nature, Scopus, NASA ADS, IEEE, Web of Science, Zenodo, DataCite,
                            PLOS, NASA NTRS, Figshare, OSF Preprints, LA Referencia, theses.fr, The Lens,
                            BASE, Dimensions: candidates
    ▼
WebScraping/abstracts     — OpenAlex's record of what the others found; the abstracts the records lacked
    ▼
WebScraping/screening     — score from title/abstract, flag preprints/duplicates/retractions → candidates.csv
    ▼
 (you review)             — only with `review: true`: set the `decision` column to yes/no
    ▼
WebScraping/resolve+fetch — publishers' APIs → open links → arXiv → repositories (PubMed Central, OSTI, HAL, CORE, ...);
                          only a real PDF with the right title is kept
    ▼
WebScraping/papers/*.pdf (+ .json provenance, ledger.sqlite)
    ▼
LocalExtraction's pipeline — the same tables, every cell answered → WebScraping/web_output/
```

The extraction is that of [LocalExtraction](../../LocalExtraction/README.md), so this folder needs
the `LocalExtraction/` folder beside it.

## Two ways in: keywords and DOIs

The window has one button for each: **1 · Fetch DOIs**, then **2 · Search**. Both start from the
keywords saved in the job file (`search.queries`), and both end in the same review, download and
extraction.

- **1 · Fetch DOIs** (or `mme-dois`) asks OpenAlex, Crossref, Semantic Scholar and arXiv the
  keywords, then more made of the topic and property words, and saves only the DOIs, in
  `search.doi_list` (`WebScraping/Fetch_DOIs/dois.csv`) — a wide net (tens of thousands of DOIs, many
  off topic). The window shows how many are saved, and when they were fetched.
- **2 · Search** fetches no DOI itself: it searches with what is saved — the keywords, asked of each of
  the 25 search sources, and the saved DOIs. Its steps, shown under the buttons (▶ under way, ✓ done):
  ① keywords in the sources → ② check the new papers and the saved DOIs — each DOI new to the project
  gets its OpenAlex record (abstract, open copies) — → ③ score them all on the topic and propose those
  with a legal copy known. A DOI not looked up yet (the search stopped first) is not scored on its bare
  title: the next search looks it up first. With no DOI saved, it says so and offers to search with the
  keywords only.
- **After 2 · Search, download the papers proposed** (a box under the buttons): the search goes on by
  itself into 3 · Download, and — with **then extract them** — into 4 · Extract: one click from the
  search to the database. A search stopped, or one that failed, goes no further. **then extract them**
  also extracts the PDFs downloaded before and not extracted yet, not only what the download brought.
- In the terminal, `mme-web` does both in one command when `search.collect_dois: true` (Fetch DOIs
  first); `mme-web --dois` checks the saved DOIs and downloads what is on topic, without a keyword search.

## The stages

1. **Discover** — every query in the job is asked of every search source (`search.sources`, see
   [Where papers are searched for](#where-papers-are-searched-for)): OpenAlex (journals, arXiv and
   ChemRxiv alike; it also says whether and where a legal open-access copy exists, and flags
   retractions), arXiv and the twenty-three others. A list of DOIs / links / arXiv ids you already know
   can be added (`search.ids_file`), and the DOI list of Fetch DOIs is taken in (`search.doi_list`, see
   [Two ways in: keywords and DOIs](#two-ways-in-keywords-and-dois)). Then what was found is completed: a paper another source found is
   looked up in OpenAlex (its open copies, a retraction), and a paper whose record came without an
   abstract has one asked for (`search.abstract_sources`) — see [Missing abstracts](#missing-abstracts).
2. **Screen** — each candidate gets a score from its title and abstract (a topic word and a
   property word must both appear; a word in the title counts 2, in the abstract 1; each exclude
   word costs 3), and flags: `preprint`, `review`, `RETRACTED`, `no-abstract` (no service had one),
   `no-open-copy-known`,
   `duplicate-of:<paper>` (a preprint and its journal version are one paper; the published, fetchable
   one wins). The result is `WebScraping/papers/candidates.csv` — open it in a spreadsheet, sorted best
   first, with a `why` column showing which words scored. The `access` column says how a copy is
   expected to be had: `open`, through a publisher's API (`elsevier`, `wiley`), or `closed` — no
   open copy is known to the search. A closed paper is not proposed, unless the job sets
   `screen.propose_closed`: then the fetch stage asks the repositories for the authors' manuscript.
3. **Review** — only when the job sets `review: true` (`configs/sse.yaml` does not:
   the proposals are approved and fetched straight away). Set `decision` to `yes` or `no` (empty =
   still waiting) and save. The file may be saved by Excel with `;` between columns or in
   Windows-1252: both are read.
4. **Fetch** — for each approved paper the sources are tried in the job's order (`fetch.sources`,
   see [Where a copy is looked for](#where-a-copy-is-looked-for)): the publisher's own API, the
   open links OpenAlex knows (a landing page is followed to the PDF it declares for search
   engines), Unpaywall, arXiv, then the repositories. A file is kept only if it is a real PDF (not the
   paywall page a server sometimes sends under a `.pdf` name), at least article-sized, and its
   first pages carry the paper's title (not a supplement or another article). A refusal (401/403)
   or a `robots.txt` "Disallow" just means "next source" — nothing tries to get around one.
   Failures are retried on the next runs, three attempts in all; a paper with no legal copy is
   marked `closed` ("needs a manual PDF": drop it into `LocalExtraction/papers/` and Project 1 handles it).
5. **Extract** — Project 1's pipeline over `WebScraping/papers/`, with the metadata the source reported
   (a better title, journal and DOI than can be guessed from a PDF's first page) — what the source
   did not report (a license, an OpenAlex id) is completed from OpenAlex — and only the data you
   asked for (`extract.properties`, `extract.require_material`). Every cell of every table is
   answered, as in [LocalExtraction](../../LocalExtraction/README.md#no-open-answer). The result goes to
   `WebScraping/web_output/` (`--output` to choose another folder), apart from that of your own PDFs.
   Each run **appends** the papers it fetched to the tables already there, never losing a row — see
   [Adding papers to a database](../../LocalExtraction/README.md#adding-papers-to-a-database).

## What lands where

| Path | What |
|---|---|
| `WebScraping/papers/<doi>.pdf` | A fetched paper, named from its DOI (`arxiv_<id>.pdf` for an arXiv-only paper), so its `paper_id` is stable across runs |
| `WebScraping/papers/<doi>.json` | Its provenance: DOI, title, source, URL, license, retrieval date, SHA-256, page count, how well the title matched |
| `WebScraping/papers/ledger.sqlite` | One row per paper ever found, with its status: new → screened → approved/rejected → downloaded/closed/failed → extracted |
| `WebScraping/papers/candidates.csv` | The review list |
| `WebScraping/web_output/` | The database of the web papers. In its `papers.csv`, `origin` = `web`, with `source_service`, `source_url`, `license`, `retrieved_at`, `file_sha256`, `openalex_id` and `metadata_basis` |

`WebScraping/papers/` and `WebScraping/averageScrap/.env` are git-ignored: the PDFs are someone else's copyright and the keys are secret.

## The job file

`configs/sse.yaml` is a ready-made example for solid-state electrolytes. It sits in the project's
`configs/` folder, not in `WebScraping/`, next to the other settings of the project. Every key is optional
except `search`; a key the loader does not know is an error (a misspelled `min_score` would
otherwise quietly keep its default).

| Key | Meaning |
|---|---|
| `contact_email` | Sent to OpenAlex, Crossref and Unpaywall as the contact for polite use of their free APIs (Unpaywall requires one). Or set `MME_EMAIL`. It is never sent anywhere else |
| `search.queries` / `ids_file` / `years` / `sources` | What to search for, papers you already know, `[first, last]` year, and where to search (default: all of [this table](#where-papers-are-searched-for)) |
| `search.abstract_sources` | Who is asked, in this order, for the abstract a record lacked (default: `openaire, crossref, europepmc, semanticscholar, springernature, scopus, core, ads, ieee, plos`; `[]`: nobody) |
| `search.max_per_query`, `include_preprints` | How many candidates each source returns for each query (default 200) and whether preprints count |
| `screen.topic_words`, `property_words`, `exclude_words`, `min_score` | The screening rule above |
| `screen.review` | `false` (as in `sse.yaml`): fetch the proposals straight away — one command does everything. `true` (the default of a job file that does not say): stop after screening so you can review |
| `screen.propose_closed` | `false` (default): a paper no open copy is known for is not proposed. `true`: it is, and the fetch stage asks every source for a copy; the ones nobody has end as `closed` — your list of papers to get by hand |
| `fetch.folder`, `sources`, `workers`, `max_pdf_mb` | Where PDFs go (`WebScraping/papers`), the sources and the order they are tried in (default: all of the table below), parallel downloads (3), size cap (60 MB) |
| `extract.properties` | The wished data: only these properties are exported (empty = every property); names as in `properties.csv`, e.g. `Activation_Energy` — which covers migration barriers and every other name of it (a job file that still lists `Migration_Barrier` keeps working) |
| `extract.require_material` | Drop a numeric value that cannot be tied to a material (otherwise it goes to `unassigned_values.csv`) |

## Where papers are searched for

Every source of `search.sources` is asked every query (up to `max_per_query` papers each); the same
paper found by several of them is one candidate (by its DOI), and `found_by` says who found it. A
source that needs a key is skipped — with a line saying so — until the key is in
`WebScraping/averageScrap/.env`, where an empty line is waiting for it. Every key here is free.

| `search.sources` | What it is | Needs |
|---|---|---|
| `openalex` | The main index: journals, arXiv and ChemRxiv alike, with where an open copy is and retractions | — |
| `arxiv` | The preprints (`search.arxiv_categories`). When arXiv answers "too many requests" (HTTP 429, a limit per network address), the run goes on through OpenAlex's copy of the arXiv catalogue — the same papers with their arXiv PDF, without the subject categories | — |
| `crossref` | The registry of every DOI: journal articles and preprints, with the abstracts the publishers deposited | — |
| `semanticscholar` | Semantic Scholar's own search over journals and preprints | — (`SEMANTIC_SCHOLAR_API_KEY` makes it steadier) |
| `europepmc` | PubMed, PubMed Central and the preprint servers (ChemRxiv, Research Square, ...) | — |
| `openaire` | The European research graph: repositories, theses, Zenodo — often the abstract a journal record lacks | — |
| `doaj` | The Directory of Open Access Journals: every article can be read by anyone | — |
| `jstage` | Japan's journals (J. Ceram. Soc. Jpn., *Electrochemistry*, ...) | — |
| `core` | The full texts of the world's repositories — its search reads the full text, not only the abstract | `CORE_API_KEY`: https://core.ac.uk/services/api |
| `springernature` | Springer, Nature and BioMed Central journals, with their abstracts | `SPRINGER_NATURE_API_KEY`: https://dev.springernature.com/ (Basic plan) |
| `scopus` | Elsevier's index of every publisher's journals | `ELSEVIER_API_KEY` (the one of [Elsevier](#elsevier--sciencedirect)) |
| `ads` | NASA ADS: the physics literature, each journal paper with its arXiv version | `ADS_API_TOKEN`: https://ui.adsabs.harvard.edu/ → Settings → API Token |
| `ieee` | IEEE Xplore: the IEEE's journals and conferences (200 requests a day) | `IEEE_API_KEY`: https://developer.ieee.org/ |
| `wos` | Web of Science Core Collection, through its Starter API (titles and DOIs) | `WOS_API_KEY`: https://developer.clarivate.com/apis/wos-starter (Free Trial: 50 requests a day) |
| `zenodo` | CERN's open repository: papers, preprints, theses and reports deposited by their authors — often the free copy of a journal article, under the journal's DOI | — |
| `datacite` | The DOI registry of repositories and research centres: the papers, theses and reports they keep (arXiv's DOIs are left to `arxiv`) | — |
| `plos` | Every PLOS article, open access under CC BY, with its PDF (PLOS allows ten searches a minute: about 25 minutes for 233 queries, once a month) | — |
| `ntrs` | NASA's Technical Reports Server: reports, conference papers and articles released for public use | — |
| `figshare` | The repository of many universities (theses, papers) and former home of TechRxiv; the supporting-information files it also lists are left out | — |
| `osf` | The preprint servers OSF hosts — ECSarXiv (the Electrochemical Society's), engrXiv, EarthArXiv, … — through SHARE | — |
| `lareferencia` | The open repositories of Latin America and Spain: articles and theses, many in Spanish or Portuguese | — |
| `thesesfr` | Every doctoral thesis defended in France, with its abstract, and its full text (in HAL) when public | — |
| `lens` | The Lens: 250 million works merged from Crossref, PubMed, OpenAlex and others | `LENS_API_TOKEN`: through your institution's subscription, or a non-commercial trial — https://www.lens.org/lens/user/subscriptions → API & Data |
| `base` | BASE (Bielefeld): 400 million documents from 11,000 repositories | `BASE_ACCESS=yes`, once BASE has registered your network's IP address (free for non-commercial research): https://www.base-search.net/about/en/contact.php |
| `dimensions` | Dimensions: 140 million publications with their abstracts | `DIMENSIONS_API_KEY`: free for non-commercial scientometric research, on application — https://www.dimensions.ai/scientometric-research/ |

### Missing abstracts

Screening reads the title and the abstract, and many records come without the abstract: OpenAlex
does not carry Elsevier's (in the October 2026 run, 219 Elsevier papers were declined on their
title alone), and Scopus, J-STAGE and Web of Science give none. So before screening, each paper
without an abstract is asked about, in the order of `search.abstract_sources`, until one service
has it: OpenAIRE (it held half the missing Elsevier abstracts in a sample), Crossref, Europe PMC,
Semantic Scholar, Springer Nature (its own papers), Scopus (on your university's network, or with
`ELSEVIER_INSTTOKEN`), CORE, NASA ADS, IEEE and PLOS (their own papers). Each service is asked about a paper
once — one added to the job, or given its key, later is asked on the next run — and a paper that
was declined for want of an abstract is screened again once one is found. The `abstract_from`
column of `candidates.csv` says where each abstract came from, or who was asked.

What is not used, and why: ChemRxiv's and SciELO's own interfaces (behind a bot check that turns
programs away; OpenAlex, Crossref, Europe PMC and DOAJ list their papers anyway), CiNii (unavailable
when tested), Internet Archive Scholar (no interface for programs; its catalogue fatcat did not
answer), Research Square, Preprints.org, TechRxiv and SSRN (their preprints are registered with
Crossref, so `crossref` and `openalex` find them), CNKI, Wanfang and the other paid national
databases, Google Scholar, ResearchGate and Academia.edu (no interface for programs, and their
terms forbid scraping), and the shadow libraries (Sci-Hub, LibGen, Anna's Archive, Z-Library),
which distribute copyrighted papers unlawfully.

## The watcher

A site that limits requests ("too many requests", HTTP 429), is busy (HTTP 5xx) or does not answer
refuses a check that would work a little later: the search of one keyword in one source, or the
lookups and the download of one DOI. Such a check is not taken for an answer — not "nothing found",
not "no legal copy". The watcher ([`watcher.py`](watcher.py)) puts it on its **watch list** (a table
of `ledger.sqlite`, so it survives the end of the run), checks it again after **2, 5, 10 then 15
minutes** — the status line counts down; Pause holds the wait and Stop ends it — and leaves what is
still refused for the next run, which checks it first. A refused try does not count against a
paper's three tries; a check refused six times (a service that is gone, not busy) is given up.
A source that refuses three searches in a row is not asked the rest now: they go on the list unasked.

At the end of each step it reports what was checked — in the log, and on the step's card. It looks
like this (the numbers are an example):

```
Watcher report — this run:
  keywords checked: 233 (231 answered by at least one source; 2 with a source still waiting)
  searches (keyword × source): 5,592 asked, 5,571 answered, 21 refused, 19 answered on a later try; 233 already done in the last 30 days
  DOIs checked: 620 — 431 downloaded (12 on a later try), 150 with no legal copy, 37 failed, 2 still refused (waiting)
In total (every run): 233 keywords answered in full by at least one source; 4,433 DOIs checked (…); waiting on the watch list: 2 searches (2 keywords) and 2 DOIs.
```

Fetch DOIs (`mme-dois`) has the same rounds for the keyword searches a source refused, and ends with
its own report: keywords checked, searches asked / answered / answered on a later try / still
refused, DOIs given by the sources, new, and in the list.

## Where a copy is looked for

Every source is a place that may lawfully give the paper to a program: the publisher's own
interface for it, an open-access link, or a repository the authors or their funder deposited the
paper in. They are tried in this order; a later one is only asked when the ones before it gave
nothing that could be kept.

| `fetch.sources` | What it is | Needs |
|---|---|---|
| `elsevier` | Elsevier's API: its open-access articles, and those your institution subscribes to | `ELSEVIER_API_KEY` (free) |
| `wiley` | Wiley's text-and-data-mining API: its open-access articles, and subscribed ones from your university's network | `WILEY_TDM_TOKEN` (free) |
| `aps` | The American Physical Society's API for its open-access articles (Physical Review ...) | — |
| `openalex` | The links the search records carry: the open-access files OpenAlex and the other search sources found (Zenodo, NTRS, OSF, Figshare, PLOS, …), then the repository pages that hold a copy (LA Referencia, theses.fr, BASE, DataCite — shown as `repository` in `source_service`), then the paper's own page when it is open | — |
| `unpaywall` | The open-access links Unpaywall knows, often more repository copies | a contact email |
| `publisher` | The article's own page at an open-access journal (MDPI, Frontiers, PLOS, Copernicus, BMC, Nature Communications, RSC Advances, …) or one an index says is open there: the PDF the page declares. Where the DOI points is asked of the DOI system first, so that the publisher's own robots.txt is the one consulted | — |
| `arxiv` | The paper's arXiv version | — |
| `pmc` | PubMed Central's open-access set, read from the copy NCBI keeps in the cloud for programs | — |
| `osti` | OSTI.GOV: the accepted manuscript of work funded by the US Department of Energy | — |
| `hal` | HAL, the French open archive: the file deposited by the authors | — |
| `zenodo` | The file the authors deposited in Zenodo under the article's DOI | — |
| `datacite` | The copies university and research-centre repositories registered with DataCite as another form of the article (its accepted manuscript, its preprint) | — |
| `semanticscholar` | The arXiv version Semantic Scholar matched to a journal paper, and the repository copy it knows | — (`SEMANTIC_SCHOLAR_API_KEY` makes it steadier) |
| `ads` | The arXiv version NASA ADS matched to a journal paper, and the scan of an older article ADS keeps | `ADS_API_TOKEN` (free) |
| `openaire` | The copies in the university and national repositories OpenAIRE harvests | — |
| `core` | The copies CORE harvested from the world's repositories | `CORE_API_KEY` (free) |
| `crossref` | The links publishers register with Crossref for text mining (Springer, IOP and the Electrochemical Society, ...), followed like any page: robots.txt and a refusal are respected | — |

The last ten look a paper up by its DOI, which is how a paper the search calls closed can still
arrive: its authors' manuscript sits in a repository (`screen.propose_closed`). What a repository
holds is usually that accepted manuscript — the same text and numbers as the journal's version,
not its layout. `source_service` in `papers.csv` says where each file came from.

`python -m WebScraping --check` shows which of these can be reached from where
you are and whether your keys work.

What to expect, from a sample of the solid-electrolyte job (October 2026): of 40 open-access
papers, OpenAlex's links and arXiv alone delivered 16, and the repositories brought that to 23
(PubMed Central 4, OpenAIRE 2, HAL 1). Of the 17 that still failed, 10 were open-access papers of
Wiley and Elsevier, whose web pages refuse scripts — that is what their two free keys are for —
and the others sat behind a bot check (MDPI, RSC, ChemRxiv, one repository). Of 40 papers the
search called closed, 1 had a deposited manuscript (OSTI): `screen.propose_closed` is worth
switching on for the list of papers to get by hand more than for the downloads.

## Elsevier / ScienceDirect

Elsevier papers are fetched through Elsevier's own API — the sanctioned way to read, by machine,
what a subscription includes — not by scraping ScienceDirect pages. You need:

1. an **API key** (free): https://dev.elsevier.com/ → "I want an API key", created while you are
   on your university's network;
2. the key in `WebScraping/averageScrap/.env` (or **API keys…** in the window): `ELSEVIER_API_KEY=...`;
3. to run from the **university network or VPN** — the API only returns full texts for the
   institution the key belongs to — or to ask Elsevier for an **institutional token**
   (`ELSEVIER_INSTTOKEN=...`), which lets the key work from anywhere.

Run `python -m WebScraping --check` to see exactly what your key can do
(key accepted? full text as XML? as PDF?). Elsevier limits use to non-commercial text mining and to
a weekly quota; when the quota or the key is refused the Elsevier source is switched off for the
rest of the run. Without a key, Elsevier papers can only come from open-access copies.

**Not on the university's network, and no institutional token?** Then closed Elsevier papers are not
downloaded — every open copy still is. Each refused paper says *not entitled*, and the end of the
download says how many there were and why. They are not given up on: a refusal for where the request
comes from does not count as a failed try, so the next **3 · Download**, from campus or the VPN, asks
again. A one-page PDF from Elsevier (what its API sends when the subscription does not cover a paper)
is refused, never saved as the paper.

## Wiley

Wiley's web pages turn scripts away, also for open-access articles; its text-and-data-mining API
is the way it offers instead. Sign in at
https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining, accept the agreement,
and put the token in `WebScraping/averageScrap/.env`: `WILEY_TDM_TOKEN=...`. It fetches Wiley's open-access articles from
anywhere and the subscribed ones from your university's network, at no more than 60 requests in
10 minutes (the program waits accordingly). `--check` tells you whether the token works.

## Good citizenship

Every service is used through the interface it offers to programs, with your contact address in
the User-Agent when you give one. Requests are spaced per host (arXiv: 3 s for its API; 15 s
between PDF downloads, as its `robots.txt` asks of generic crawlers — `Crawl-delay` is obeyed for
every site), retried with back-off, and `robots.txt` is honoured for every file or page, as RFC 9309
reads it (its `*` and `$` wildcards, the longest rule winning); a service
that keeps answering "too many requests" is left alone for the rest of the run. Nothing here
bypasses a paywall, a login, a bot check or a refusal, and shadow libraries (Sci-Hub and the like)
are not used and cannot be added as a source: they hand out papers without the right to. Papers
with no legal copy stay a manual step — your library, an inter-library loan, or a request to the
authors.

## Known limitations

- **The web project reads only what it may.** A paper with no open copy (and, for Elsevier or
  Wiley, no key or no entitlement from where you run) is marked `closed` and needs a manual PDF.
  Many publishers' servers answer a scripted download of even an open-access paper with 403; that
  is respected, and another lawful copy is the way round it: the publisher's API (with its free
  key), PubMed Central, a repository, a preprint. If Elsevier's API only returns a paper as XML,
  it is not extracted yet — a reader for it is the next step.
- **Screening works from the title and abstract**, so a paper whose abstract does not mention the
  property is not proposed (the `why` column shows what scored). Reviewing the list is the
  safeguard; `--yes` removes it. CORE's search reads full texts, so it finds some of those papers.
- **J-STAGE's PDFs are closed to programs** (its robots.txt says so): a J-STAGE paper is found, but
  its copy has to come from another source or by hand.

## Tests

```bash
python -m pytest WebScraping          # or: python -m unittest discover -s WebScraping/tests -t . -v
```

They run offline: every network call is answered by a fake session. `tests/test_gui.py` builds the
window (transparent, on a made-up database and ledger) and drives it; without a screen those tests
are skipped.
