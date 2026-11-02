# WebScraping — Part 2

A part of [MoukhlijMatExtract (MME)](../README.md). It finds papers on the web and extracts them
with the [LocalExtraction](../LocalExtraction/README.md) pipeline. **Two methods, one database:**
both save their PDFs in `WebScraping/papers/` and write their results into `WebScraping/web_output/`
(the same files as part 1). Run either, or both — the second only adds what the first did not get.

Work inside the project's virtual environment (`.venv/`); see the
[main README](../README.md#install-once) for the one-time setup (`make install`), and enter it in
every terminal (`source .venv/bin/activate`). Method 2 also needs its own packages and Google
Chrome — see the [moukhlij4scraping README](moukhlij4scraping/README.md).

```
                          ┌─ method 1 · averageScrap ──────────── search open sources ─┐
configs/sse.yaml ─────────┤                                                             ├─▶ WebScraping/papers/ ─▶ extract ─▶ WebScraping/web_output/
                          └─ method 2 · Fetch_DOIs + moukhlij4scraping ─ DOIs → PDFs ──┘
```

| | Folder | What it does |
|---|---|---|
| **Method 1 — search open sources** | `averageScrap/` | Search 14 services (OpenAlex, arXiv, Crossref, Semantic Scholar, …) by keyword, keep the papers worth reading, download the legal copies, extract. [Details](averageScrap/README.md) |

## The one GUI

```bash
make gui                  # the whole project → “2 · Web scraping” → pick a method
python -m WebScraping gui  # just the web two-method chooser
```

Method 1 shows the search / review / download / extract window. Method 2 shows three buttons —
**Fetch DOIs → Scrape articles → Extract** — that run the steps below and stream their output.

## From the terminal

```bash
# Method 1 (the default)
python -m WebScraping                  # search, screen, download, extract (configs/sse.yaml)
python -m WebScraping --check          # test the setup (network, API keys, folders)
python -m WebScraping --stage extract  # only extract what is already in WebScraping/papers/

# Method 2
python WebScraping/Fetch_DOIs/get_dois.py --count 500                  # 1. add 500 new DOIs → dois.csv + dois.txt
python WebScraping/moukhlij4scraping/run.py --from-fetch -l WebScraping/papers   # 2. PDFs (reads dois.txt)
python -m WebScraping --stage extract                                 # 3. extract → WebScraping/web_output/
```

**How many DOIs (step 1).** Each run *adds* new DOIs to the list already saved. `--count N` (1 or more)
adds N new ones and stops; without it there is no limit — the search goes on until you press Ctrl-C (or
**Stop** in the window, which always asks how many first), and every DOI found is kept. The new DOIs are
shared out over all the keywords, so they come from the whole topic. Re-running the same keywords mostly
finds DOIs already in the list, so when they run dry the search goes on with more keywords made of the
job file's own topic and property words (`screen.topic_words` × `screen.property_words`, thousands of
them); `--no-expand` keeps to the keywords given. `make doi COUNT=500` does the same as `--count 500`.

Keys and your e-mail (all free, all optional) live in `WebScraping/averageScrap/.env`. Set them in
the window with **API keys…** (in the chooser and in both method windows): one card per
organization, saying what its key opens, which method uses it and whether it is set, with a
**Get a free key ↗** button to its sign-up page. Full options
and the job-file format are in the [method 1 README](averageScrap/README.md); method 2's own notes,
including that it does not only fetch open-access copies, are in the
[moukhlij4scraping README](moukhlij4scraping/README.md).
