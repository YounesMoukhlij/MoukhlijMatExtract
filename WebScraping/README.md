# WebScraping — Part 2

A part of [MoukhlijMatExtract (MME)](../README.md). It finds papers in the **open sources** of the
scholarly literature, downloads their **legal open-access copies** and extracts them with the
[LocalExtraction](../LocalExtraction/README.md) pipeline. The PDFs go into `WebScraping/papers/` and the
results into `WebScraping/web_output/` (the same files as part 1).

Work inside the project's virtual environment (`.venv/`); see the
[main README](../README.md#install-once) for the one-time setup (`make install`), and enter it in
every terminal (`source .venv/bin/activate`).

```
configs/sse.yaml ─▶ 1 · search (25 services) ─▶ review ─▶ 2 · download (legal copies) ─▶ WebScraping/papers/ ─▶ 3 · extract ─▶ WebScraping/web_output/
```

The code is in [`averageScrap/`](averageScrap/README.md): it searches 25 services (OpenAlex, arXiv,
Crossref, Semantic Scholar, Europe PMC, Zenodo, theses.fr, …) by keyword, keeps the papers worth reading, downloads the legal
copies (Unpaywall, arXiv, PubMed Central, OSTI, HAL, the publishers' text-mining APIs with your keys) and
extracts them.

## The window

```bash
make gui                   # the whole project → “2 · Web scraping”
python -m WebScraping gui  # just the Web scraping window
```

It asks for your contact e-mail first, then shows **2 · Search → 3 · Download → 4 · Extract**, the
candidates to review, and a results card after each step. **Pause** holds a step (what is under way
finishes first); **Stop** ends it, and the next run goes on where it stopped. When the internet goes, the
step says so and waits for it to come back.

## From the terminal

```bash
python -m WebScraping                  # search, screen, download, extract (configs/sse.yaml)
python -m WebScraping --check          # test the setup (network, API keys, folders)
python -m WebScraping --stage extract  # only extract what is already in WebScraping/papers/
```

Keys and your e-mail (all free, all optional) live in `WebScraping/averageScrap/.env`. Set them in the
window with **API keys…**: one card per organization, saying what its key opens and whether it is set,
with a **Get a free key ↗** button to its sign-up page. Full options and the job-file format are in the
[averageScrap README](averageScrap/README.md).
