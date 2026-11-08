# Contributing to MoukhlijMatExtract

Thanks for your interest in improving MoukhlijMatExtract (MME). This is a research tool, so
correctness of the extracted data matters most — changes that touch the pipeline should keep the
guarantee that **no data cell is ever left empty** (every value carries a `basis`).

## Set up

You need **Python 3.11+** and, for scanned pages, **Tesseract** (`brew install tesseract` on macOS,
`sudo apt install tesseract-ocr python3-tk` on Debian/Ubuntu). From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                   # the package and the test tools
python -m spacy download en_core_web_sm
```

(`make install` sets up the same venv from `requirements.txt` if you prefer.)

## Run the tests

```bash
make test        # or: python -m pytest
```

All tests must pass before you open a pull request. They run offline (network calls are faked).

## Making changes

- Keep each part self-contained: parts 1–2 build the databases, parts 3–4 read them.
- If you change extraction, add or update a test in `LocalExtraction/tests/` — especially keep
  `PipelineTests.test_no_table_has_an_open_cell` (asserts every output table is complete) and the
  no-open-answer tests passing.
- Match the existing style (clear names, short comments that explain *why*). Update the relevant
  README and `CHANGELOG.md` under an **Unreleased** heading.
- Work on a branch and open a pull request against `main` with a short description of what and why.

## License of contributions

MoukhlijMatExtract is licensed under the GNU AGPL-3.0-or-later (see `LICENSE`). By contributing, you agree
that your contribution is licensed under the same terms.

## Reporting issues

Open a GitHub issue with: what you ran, what you expected, what happened, and (if extraction-related)
a minimal example paper or snippet. For anything sensitive, email younes.moukhlij@usms.ac.ma.
