# mme_gui/tests/test_commands.py
"""Every command of the project can be run, and is documented, everywhere a user or a reviewer looks:
- every option of every command can be given through its make target;
- docs/COMMANDS.md names every command and every one of its options;
- `mme` lists every command and runs every part;
- docs/MANUAL.md only names make targets and documents that exist."""

import io
import re
import unittest
from contextlib import redirect_stdout

from mme_gui import commands, manual

ROOT = manual.ROOT
# The make target that runs each command, and the targets that may hold some of its options too.
MAKE_TARGET = {"mme": None, "mme-gui": "gui", "mme-local": "local", "mme-local gui": "local-gui", "mme-dois": "doi",
               "mme-web": "web", "mme-web gui": "web-gui", "mme-web coverage": "coverage", "mme-web update": "update", "mme-rank": "rank", "mme-rank gui": "rank-gui",
               "mme-classify": "classify", "mme-classify gui": "classify-gui", "mme-ml-export": "ml-export", "mme-ml-export gui": "ml-gui", "mme-eval sheet": "eval-sheet",
               "mme-eval score": "eval-score", "mme-eval agree": "eval-agree",
               "mme-eval benchmark": "eval-benchmark", "mme-eval gold": "eval-gold",
               "mme-eval reference": "eval-reference", "mme-release": "release"}
_OPTION = re.compile(r'(?<![\w-])(--[a-z][a-z-]+)')


def usage_options(command: manual.Command) -> set:
    """The options a command takes, read from the usage lines of its --help (not from its examples)."""
    ok, text = manual.help_text(command)
    assert ok, text
    usage = text.split("\n\n", 1)[0]
    return set(_OPTION.findall(usage)) - {"--help", "--version"}


def makefile() -> str:
    return (ROOT / "Makefile").read_text(encoding="utf-8")


def recipe_options(target: str) -> set:
    """Every --option the recipe of a make target can pass, its option variables expanded."""
    text = makefile()
    variables = {}
    for m in re.finditer(r'(?m)^([A-Z_]+)\s*=\s*((?:.*\\\n)*.*)$', text):
        variables[m.group(1)] = m.group(2)
    recipe = re.search(rf'(?m)^{re.escape(target)}:.*\n((?:\t.*\n?)+)', text)
    assert recipe, f"no make target {target}"
    body, seen = recipe.group(1), set()
    while True:
        names = set(re.findall(r'\$\(([A-Z_]+)\)', body)) - seen
        if not names:
            break
        seen |= names
        body += " " + " ".join(variables.get(name, "") for name in names)
    return set(_OPTION.findall(body))


class MakeCoversEveryOptionTests(unittest.TestCase):
    def test_every_command_has_its_make_target(self):
        self.assertEqual(set(MAKE_TARGET), {c.name for c in manual.COMMANDS})

    def test_every_option_of_every_command_can_be_given_with_make(self):
        for command in manual.COMMANDS:
            target = MAKE_TARGET[command.name]
            if target is None:
                continue
            with self.subTest(command=command.name):
                missing = usage_options(command) - recipe_options(target)
                self.assertEqual(missing, set(), f"make {target} cannot pass {sorted(missing)}")


class ReferenceTests(unittest.TestCase):
    def test_the_reference_names_every_command_and_every_option(self):
        text = (ROOT / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
        for command in manual.COMMANDS:
            with self.subTest(command=command.name):
                self.assertIn(f"## {command.name}\n", text, "make commands")
                section = text.split(f"## {command.name}\n", 1)[1].split("\n## ", 1)[0]
                missing = sorted(o for o in usage_options(command) if o not in section)
                self.assertEqual(missing, [], f"docs/COMMANDS.md is out of date: make commands ({missing})")

    def test_the_reference_holds_no_path_of_this_computer(self):
        from pathlib import Path
        self.assertNotIn(str(Path.home()), commands.reference(markdown=True, commands=manual.COMMANDS[:2]))


class MmeTests(unittest.TestCase):
    def test_help_lists_every_command(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(commands.main(["help"]), 0)
        for command in manual.COMMANDS:
            self.assertIn(command.name, out.getvalue())

    def test_every_part_runs_its_command(self):
        for part in commands.PARTS:
            with self.subTest(part=part):
                import subprocess, sys
                # UTF-8, as the manual reads a help: on Windows a pipe is cp1252, which has no "β" or "→"
                env = dict(__import__("os").environ, PYTHONIOENCODING="utf-8")
                result = subprocess.run([sys.executable, "-m", "mme_gui.commands", part, "--help"],
                                        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT), timeout=120,
                                        env=env)
                self.assertEqual(result.returncode, 0, result.stderr[-400:])
                self.assertIn("usage:", result.stdout)

    def test_every_installed_command_is_one_part_of_mme(self):
        import tomllib
        scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
        self.assertEqual({name[len("mme-"):] for name in scripts if name != "mme"}, set(commands.PARTS))


class ManualTests(unittest.TestCase):
    def test_every_make_target_the_manual_names_exists(self):
        text = (ROOT / "docs" / "MANUAL.md").read_text(encoding="utf-8")
        targets = set(re.findall(r'`make ([a-z][a-z-]*)', text))
        # ... and the bare names after "`make x`, " in the table of § 11: `local-gui`, `web-check` ...
        targets |= {t for row in re.findall(r'(?m)^\|[^\n]*`make [a-z][^\n]*$', text)
                    for t in re.findall(r'`([a-z][a-z-]*)`', row.split("`make ", 1)[1])}
        defined = set(re.findall(r'(?m)^([a-z][a-z-]*):', makefile()))
        self.assertTrue(targets)
        self.assertEqual(sorted(targets - defined - {"make"}), [])

    def test_every_document_the_manual_links_exists(self):
        text = (ROOT / "docs" / "MANUAL.md").read_text(encoding="utf-8")
        for link in set(re.findall(r'\]\(([A-Z_]+\.md)', text)):
            with self.subTest(link=link):
                self.assertTrue((ROOT / "docs" / link).exists(), link)


if __name__ == "__main__":
    unittest.main()
