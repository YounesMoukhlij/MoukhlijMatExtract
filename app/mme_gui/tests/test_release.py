# mme_gui/tests/test_release.py
"""What a release needs to be consistent: one version everywhere, and a publishing workflow that refuses a tag that
is not that version."""

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # the repository


class ReleaseTests(unittest.TestCase):
    def test_the_version_is_the_same_in_the_package_and_its_citation(self):
        version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        cited = re.search(r'^version:\s*"?([^"\s]+)"?', (ROOT / "CITATION.cff").read_text(encoding="utf-8"), re.M)
        self.assertEqual(cited.group(1), version)

    def test_the_publishing_workflow_runs_on_a_tag_and_checks_it(self):
        workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
        self.assertIn('tags: ["v*"]', workflow)
        self.assertIn('test "${GITHUB_REF_NAME}" = "v${version}"', workflow)
        self.assertIn("twine check --strict", workflow)
        self.assertIn("environment: pypi", workflow)
        self.assertNotRegex(workflow, r"(?i)password|api[_-]?token")  # trusted publishing: no token anywhere


if __name__ == "__main__":
    unittest.main()
