# web/__init__.py
"""Project 2 — the web side of AutoMatExtract.

Finds papers online (OpenAlex, arXiv), keeps the ones worth reading, fetches a legal copy of each
into papers/web/ (open-access sources first, Elsevier's own API for what a subscription includes)
and hands the PDFs to the same extraction pipeline Project 1 uses. Nothing here parses a paper:
discovery, screening and fetching end at a PDF in a folder.
"""
