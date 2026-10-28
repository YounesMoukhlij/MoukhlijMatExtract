# WebScraping/__init__.py
"""Project 2 of MoukhlijMatExtract — the web side. Two methods that feed one output folder:

  - averageScrap/        method 1: search open sources (OpenAlex, arXiv, Crossref and eleven more),
                         keep the papers worth reading, fetch the legal copies, extract them.
  - Fetch_DOIs/ +        method 2 (moukhlij4scraping): collect the DOIs of a topic, fetch a PDF for
    moukhlij4scraping/   each, extract them.

Both write their PDFs into WebScraping/papers/ and their database into WebScraping/web_output/.

    python -m WebScraping            method 1 from the terminal
    python -m WebScraping gui        the two-method chooser (or use the one project GUI: python -m mme_gui)
"""
