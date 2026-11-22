# LocalExtraction/tests/test_demo.py
"""The worked example (examples/): the two CC BY papers give the values examples/expected_values.csv lists.
A change to the extraction that changes them shows here — update the list (and examples/README.md) when
the change is an improvement."""

import tempfile
import shutil
import unittest
from pathlib import Path

import pandas as pd

from LocalExtraction.cli import run_extraction
from LocalExtraction.extractor import NLP_MODEL

_NO_MODEL = NLP_MODEL.startswith("no language model")

EXAMPLES = Path(__file__).resolve().parents[3] / "resources" / "examples"
PROPERTIES = {"activation_energy": "activation_energy_eV", "ionic_conductivity": "ionic_conductivity_S_cm",
              "electronic_conductivity": "electronic_conductivity_S_cm",
              "diffusion_coefficient": "diffusion_coefficient_cm2_s"}
KEY = ["paper_id", "property", "material_formula", "value", "attribution", "page"]


@unittest.skipUnless((EXAMPLES / "papers").is_dir(), "the examples folder is not here (installed package)")
class DemoTests(unittest.TestCase):
    @unittest.skipIf(_NO_MODEL, "the expected values are those read with a spaCy language model (python -m spacy download en_core_web_sm); without one, sentences are split by punctuation only and the extraction warns that it reads less")
    def test_the_example_papers_give_the_expected_values(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out, True)
        run_extraction(str(EXAMPLES / "papers"), str(out), max_workers=2, lookup=False)
        rows = []
        for prop, column in PROPERTIES.items():
            table = pd.read_csv(out / f"{prop}.csv", dtype=str, keep_default_na=False)
            rows += [{"paper_id": r["paper_id"], "property": prop, "material_formula": r["material_formula"],
                      "value": r[column], "attribution": r["attribution"], "page": r["page"]}
                     for _, r in table.iterrows()]
        got = sorted(tuple(row[k] for k in KEY) for row in rows)
        expected = pd.read_csv(EXAMPLES / "expected_values.csv", dtype=str, keep_default_na=False)
        self.assertEqual(got, sorted(tuple(r) for r in expected[KEY].itertuples(index=False)))


if __name__ == "__main__":
    unittest.main()
