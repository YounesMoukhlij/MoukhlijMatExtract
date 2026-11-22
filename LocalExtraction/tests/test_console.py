# LocalExtraction/tests/test_console.py
"""A console that cannot show every character (Windows when the output goes to a file or a pipe: cp1252, without ✓,
≥, −, →) never stops a command: what it cannot show is shown as “?”."""

import os
import subprocess
import sys
import unittest


class ConsoleTests(unittest.TestCase):
    def test_a_command_s_help_prints_on_a_cp1252_console(self):
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        for command in (["Evaluation", "--help"], ["MLDataset", "--help"], ["WebScraping", "run", "--help"]):
            with self.subTest(command=command):
                done = subprocess.run([sys.executable, "-m", *command], capture_output=True, env=env, timeout=120)
                self.assertEqual(done.returncode, 0, done.stderr.decode("cp1252", "replace")[-500:])
                self.assertNotIn(b"UnicodeEncodeError", done.stderr)


if __name__ == "__main__":
    unittest.main()
