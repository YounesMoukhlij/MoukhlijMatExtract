# WebScraping — Part 2

A part of [MoukhlijMatExtract (MME)](../README.md) · Author: Younes Moukhlij

Instead of collecting PDFs by hand, describe what you are looking for and let the program find the
papers, fetch the ones you can legally read, and extract from them with the pipeline of
[LocalExtraction](../LocalExtraction/README.md).

| | |
|---|---|
| **Input** | the job file `WebScraping/configs/sse.yaml` (what to search for) and the web |
| **Output** | the PDFs in `WebScraping/papers/`, and the database `WebScraping/web_output/` — the same files as [LocalExtraction's](../LocalExtraction/README.md#output) |
| **Read by** | [SelectingTopMaterial](../SelectingTopMaterial/README.md) and [Crystal and Structure Classification](<../Crystal and Structure Classification/README.md>) |

## Run it

From the project root:

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
| `--job FILE` | The job file: what to search for, which papers to keep, what to extract (default: `WebScraping/configs/sse.yaml`) |
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
free, go in `WebScraping/.env` — or in **Settings…** in the window, which writes that file. The file
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
  - **Settings…** holds the contact address and the keys (Elsevier, Wiley, CORE, ...), each with
    the address where it is had. They are saved in `WebScraping/.env`, which git ignores.
  - **Edit…** shows the job as a form — queries, years, screening words, sources, the properties
    to keep — and saves it as a job file the terminal reads too. **Check setup** is `--check`.

## How it works

```
python -m WebScraping
    │
    ▼
WebScraping/sources       — OpenAlex, arXiv, Crossref, Semantic Scholar, Europe PMC, OpenAIRE, DOAJ, J-STAGE,
                            CORE, Springer Nature, Scopus, NASA ADS, IEEE, Web of Science: candidates
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

The extraction is that of [LocalExtraction](../LocalExtraction/README.md), so this folder needs
the `LocalExtraction/` folder beside it.

## The stages

1. **Discover** — every query in the job is asked of every search source (`search.sources`, see
   [Where papers are searched for](#where-papers-are-searched-for)): OpenAlex (journals, arXiv and
   ChemRxiv alike; it also says whether and where a legal open-access copy exists, and flags
   retractions), arXiv and the twelve others. A list of DOIs / links / arXiv ids you already know can
   be added (`search.ids_file`). Then what was found is completed: a paper another source found is
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
3. **Review** — only when the job sets `review: true` (`WebScraping/configs/sse.yaml` does not:
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
   answered, as in [LocalExtraction](../LocalExtraction/README.md#no-open-answer). The result goes to
   `WebScraping/web_output/` (`--output` to choose another folder), apart from that of your own PDFs.
   Each run **appends** the papers it fetched to the tables already there, never losing a row — see
   [Adding papers to a database](../LocalExtraction/README.md#adding-papers-to-a-database).

## What lands where

| Path | What |
|---|---|
| `WebScraping/papers/<doi>.pdf` | A fetched paper, named from its DOI (`arxiv_<id>.pdf` for an arXiv-only paper), so its `paper_id` is stable across runs |
| `WebScraping/papers/<doi>.json` | Its provenance: DOI, title, source, URL, license, retrieval date, SHA-256, page count, how well the title matched |
| `WebScraping/papers/ledger.sqlite` | One row per paper ever found, with its status: new → screened → approved/rejected → downloaded/closed/failed → extracted |
| `WebScraping/papers/candidates.csv` | The review list |
| `WebScraping/web_output/` | The database of the web papers. In its `papers.csv`, `origin` = `web`, with `source_service`, `source_url`, `license`, `retrieved_at`, `file_sha256`, `openalex_id` and `metadata_basis` |

`WebScraping/papers/` and `WebScraping/.env` are git-ignored: the PDFs are someone else's copyright and the keys are secret.

## The job file

`WebScraping/configs/sse.yaml` is a ready-made example for solid-state electrolytes. Every key is optional
except `search`; a key the loader does not know is an error (a misspelled `min_score` would
otherwise quietly keep its default).

| Key | Meaning |
|---|---|
| `contact_email` | Sent to OpenAlex, Crossref and Unpaywall as the contact for polite use of their free APIs (Unpaywall requires one). Or set `MME_EMAIL`. It is never sent anywhere else |
| `search.queries` / `ids_file` / `years` / `sources` | What to search for, papers you already know, `[first, last]` year, and where to search (default: all of [this table](#where-papers-are-searched-for)) |
| `search.abstract_sources` | Who is asked, in this order, for the abstract a record lacked (default: `openaire, crossref, europepmc, semanticscholar, springernature, scopus, core, ads, ieee`; `[]`: nobody) |
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
`WebScraping/.env`, where an empty line is waiting for it. Every key here is free.

| `search.sources` | What it is | Needs |
|---|---|---|
| `openalex` | The main index: journals, arXiv and ChemRxiv alike, with where an open copy is and retractions | — |
| `arxiv` | The preprints (`search.arxiv_categories`) | — |
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

### Missing abstracts

Screening reads the title and the abstract, and many records come without the abstract: OpenAlex
does not carry Elsevier's (in the October 2026 run, 219 Elsevier papers were declined on their
title alone), and Scopus, J-STAGE and Web of Science give none. So before screening, each paper
without an abstract is asked about, in the order of `search.abstract_sources`, until one service
has it: OpenAIRE (it held half the missing Elsevier abstracts in a sample), Crossref, Europe PMC,
Semantic Scholar, Springer Nature (its own papers), Scopus (on your university's network, or with
`ELSEVIER_INSTTOKEN`), CORE, NASA ADS and IEEE (its own papers). Each service is asked about a paper
once — one added to the job, or given its key, later is asked on the next run — and a paper that
was declined for want of an abstract is screened again once one is found. The `abstract_from`
column of `candidates.csv` says where each abstract came from, or who was asked.

What is not used: Lens.org (its API is paid after a trial), Dimensions and BASE (access on
application or by registered address), ChemRxiv's own API (behind a bot check; OpenAlex, Crossref
and Europe PMC list ChemRxiv anyway), Google Scholar and ResearchGate (no interface for programs,
and their terms forbid scraping).

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
| `openalex` | The open-access links OpenAlex found with the paper: publisher, repository | — |
| `unpaywall` | The open-access links Unpaywall knows, often more repository copies | a contact email |
| `arxiv` | The paper's arXiv version | — |
| `pmc` | PubMed Central's open-access set, read from the copy NCBI keeps in the cloud for programs | — |
| `osti` | OSTI.GOV: the accepted manuscript of work funded by the US Department of Energy | — |
| `hal` | HAL, the French open archive: the file deposited by the authors | — |
| `semanticscholar` | The arXiv version Semantic Scholar matched to a journal paper, and the repository copy it knows | — (`SEMANTIC_SCHOLAR_API_KEY` makes it steadier) |
| `ads` | The arXiv version NASA ADS matched to a journal paper, and the scan of an older article ADS keeps | `ADS_API_TOKEN` (free) |
| `openaire` | The copies in the university and national repositories OpenAIRE harvests | — |
| `core` | The copies CORE harvested from the world's repositories | `CORE_API_KEY` (free) |
| `crossref` | The links publishers register with Crossref for text mining (Springer, IOP and the Electrochemical Society, ...), followed like any page: robots.txt and a refusal are respected | — |

The last eight look a paper up by its DOI, which is how a paper the search calls closed can still
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
2. the key in `WebScraping/.env` (or **Settings…** in the window): `ELSEVIER_API_KEY=...`;
3. to run from the **university network or VPN** — the API only returns full texts for the
   institution the key belongs to — or to ask Elsevier for an **institutional token**
   (`ELSEVIER_INSTTOKEN=...`), which lets the key work from anywhere.

Run `python -m WebScraping --check` to see exactly what your key can do
(key accepted? full text as XML? as PDF?). Elsevier limits use to non-commercial text mining and to
a weekly quota; when the quota or the key is refused the Elsevier source is switched off for the
rest of the run. Without a key, Elsevier papers can only come from open-access copies.

## Wiley

Wiley's web pages turn scripts away, also for open-access articles; its text-and-data-mining API
is the way it offers instead. Sign in at
https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining, accept the agreement,
and put the token in `WebScraping/.env`: `WILEY_TDM_TOKEN=...`. It fetches Wiley's open-access articles from
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
