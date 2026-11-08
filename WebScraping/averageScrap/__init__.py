# WebScraping/__init__.py
"""Project 2 — the web side of MoukhlijMatExtract (web scraping).

Finds papers online (OpenAlex, arXiv, Crossref and twenty-two more), keeps the ones worth reading, fetches a legal copy of each
into WebScraping/papers/ (open-access sources first, Elsevier's own API for what a subscription includes)
and hands the PDFs to the same extraction pipeline Project 1 uses. Nothing here parses a paper:
discovery, screening and fetching end at a PDF in a folder.

    python -m WebScraping            (from the project root; the window: python -m WebScraping gui)
"""
