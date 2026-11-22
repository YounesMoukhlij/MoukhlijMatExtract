# Publishing a release — PyPI and Zenodo

The steps to publish MoukhlijMatExtract, first on TestPyPI, then on PyPI, with a citable DOI. Run them from the
root of the repository, inside its virtual environment. Nothing here runs by itself: each step is yours.

## 0 · Before a release

| Check | Command | Must give |
|---|---|---|
| The tests | `python -m pytest -q` | every test passes |
| The worked example | `make demo` | the values of `resources/examples/expected_values.csv` (the demo test checks it) |
| A clean tree | `git status --short` | nothing: a release is built from a commit, never from uncommitted files |
| The version | `pyproject.toml` `version`, `CITATION.cff` `version` and `date-released` | the same new version; today's date |
| The changelog | `CHANGELOG.md` | "Unreleased" renamed to `[x.y.z] — YYYY-MM-DD` |
| The name | `curl -s -o /dev/null -w "%{http_code}" https://pypi.org/pypi/moukhlijmatextract/json` | `404` before the first upload (the name is free; checked 2026-11-14) |

Choose the version with [semantic versioning](https://semver.org): a release that changes extracted values is at
least a minor version (1.2.0), so that a database can always be traced to the code that made it.

### For the article

| Step | Command | Gives |
|---|---|---|
| Annotate | `mme-eval sheet`, then the workbook | the reference values (papers marked done) |
| Benchmark | `mme-eval benchmark --tool ChemDataExtractor=cde.csv` | MME against the keyword baseline and other tools |
| Gold standard | `mme-eval gold --second <2nd annotator.xlsx>` | `Evaluation/gold_standard/<name>/`: upload it to Zenodo |
| Every table and figure | `make paper` (or `make paper-docker`) | `~/MoukhlijMatExtract/paper/` with `RESULTS.md` and `environment.json` |

Run `make paper` from a clean commit: `environment.json` records `uncommitted_changes`, and a reviewer will read it.

## 1 · Build and check

```bash
rm -rf dist build
python -m pip install --upgrade build twine
python -m build                       # dist/moukhlijmatextract-x.y.z.tar.gz and -py3-none-any.whl
python -m twine check --strict dist/*
```

Look inside before uploading. Nothing of yours may be shipped:

```bash
unzip -l dist/*.whl | grep -Ei '\.env|ledger|sqlite|\.pdf|/tests/' && echo "STOP: a private file is in the wheel"
tar tzf dist/*.tar.gz | grep -Ei '\.env|ledger|sqlite|output/' && echo "STOP: a private file is in the source archive"
```

## 2 · Install the wheel in a clean environment

```bash
python3.11 -m venv /tmp/mme-check && /tmp/mme-check/bin/pip install dist/*.whl
/tmp/mme-check/bin/python -m spacy download en_core_web_sm
HOME=/tmp/mme-home /tmp/mme-check/bin/mme-local extract -i "$PWD/resources/examples/papers" -o /tmp/mme-out --offline
```

`HOME=/tmp/mme-home` keeps the check away from your own `~/MoukhlijMatExtract`. The extraction must give the 11
values of `resources/examples/expected_values.csv`. `scripts/audit/clean_install.sh` in the audit folder does all of this for
several Python versions.

## 3 · TestPyPI

1. Make an account on <https://test.pypi.org> and an API token, limited to this project after the first upload.
2. Upload:

   ```bash
   python -m twine upload --repository testpypi dist/*
   ```

3. Install from it in a new environment. The dependencies come from the real PyPI:

   ```bash
   python3.13 -m venv /tmp/mme-test
   /tmp/mme-test/bin/pip install --index-url https://test.pypi.org/simple/ \
       --extra-index-url https://pypi.org/simple/ moukhlijmatextract
   /tmp/mme-test/bin/mme --version
   ```

4. Read the project page on TestPyPI: the README must render, and its links must work.

## 4 · PyPI

```bash
python -m twine upload dist/*
```

A version can be uploaded only once: a mistake needs a new version (1.2.1), never a re-upload.

## 5 · Tag, GitHub release and Zenodo DOI

```bash
git tag -a vX.Y.Z -m "MoukhlijMatExtract X.Y.Z"
git push origin vX.Y.Z
```

1. Turn on the repository in Zenodo's GitHub settings, once.
2. On GitHub, make a release from the tag: Zenodo archives it and gives it a DOI. `.zenodo.json` fills in its
   record.
3. Put the DOI in `CITATION.cff` (`doi:`) and in the README's *Cite* section, in the next commit.

## 6 · Publishing from GitHub Actions

The workflow is in the repository: `.github/workflows/publish.yml`. Trusted publishing uploads without any token
stored anywhere. It uploads nothing until both of these are done:
1. On PyPI and on TestPyPI, add a "trusted publisher": this repository, workflow `publish.yml`, environment `pypi`
   (or `testpypi`).
2. In GitHub (Settings → Environments), make the environments `testpypi` and `pypi`, and give `pypi` "required
   reviewers": you approve each upload to PyPI.

From then on, pushing a tag `vX.Y.Z`:
- stops at once if the tag is not the version in `pyproject.toml`;
- builds and checks with `twine check --strict`;
- uploads to TestPyPI, then to PyPI once you approve.

`mme_gui/tests/test_release.py` checks that the version is the same in `pyproject.toml` and `CITATION.cff`.

## 7 · Open choices before the first upload

| Choice | Now | Suggested | Why |
|---|---|---|---|
| Development status | `5 - Production/Stable` | `4 - Beta` | the measured precision of the extraction (§ 2 of LIMITATIONS) is below what "stable" suggests to a reader of PyPI |
| Upper bounds on dependencies | none | keep none, but test `requirements.lock` and the newest versions in CI | upper bounds break installs next to other packages; a lock file records what the results were made with |
| Optional parts | everything installed | keep as is | the OCR (`pytesseract`, `opencv`) and the windows are part of normal use; splitting them out would need the code to run without them first |
