# LocalExtraction/__init__.py
"""Project 1 — the local side of MoukhlijMatExtract.

Turns a folder of battery/materials-science PDFs (papers/ by default) into a structured database
(local_output/): parses text, tables, figures and equations (OCR for scanned pages), extracts the
materials and their properties, ranks the candidates and exports linked CSV, Excel and JSON.

    python -m LocalExtraction            (from the project root; the window: python -m LocalExtraction gui)

The web project (WebScraping/) runs the same pipeline on the PDFs it fetches.
"""
