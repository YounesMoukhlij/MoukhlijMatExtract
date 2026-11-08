# LocalExtraction/tests/test_outputs.py
"""The "Delete outputs…" buttons: what each part offers to delete (only what it writes — never the
PDFs given to it), that a part in use cannot be emptied, and the dialog. Offline, in a folder made
here; files are deleted for good in the tests, never sent to the real Trash."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from LocalExtraction import outputs

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ProjectFolder(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        patcher = mock.patch.object(outputs, "send2trash", None)  # never the real Trash in a test
        patcher.start()
        self.addCleanup(patcher.stop)
        # What a project folder holds after every part has run once.
        touch(self.home / "LocalExtraction/papers/mine.pdf")
        touch(self.home / "LocalExtraction/local_output/papers.csv")
        touch(self.home / "LocalExtraction/local_output/database.xlsx")
        touch(self.home / "WebScraping/Fetch_DOIs/dois.csv")
        touch(self.home / "WebScraping/Fetch_DOIs/dois.txt")
        touch(self.home / "WebScraping/Fetch_DOIs/my notes.txt")  # not written by Fetch DOIs: never offered
        touch(self.home / "WebScraping/papers/10.1_a.pdf")
        touch(self.home / "WebScraping/papers/ledger.sqlite")
        touch(self.home / "WebScraping/web_output/papers.csv")
        touch(self.home / "SelectingTopMaterial/results/report.html")
        touch(self.home / "SelectingTopMaterial/results/my notes.txt")  # not written by the ranking
        touch(self.home / "Classification/all_materials.csv")
        touch(self.home / "Classification/crystal_structure/garnet/materials.csv")
        touch(self.home / "configs/sse.yaml")


class OutputsTests(ProjectFolder):
    def offered(self, part):
        return {group.key: sorted(str(p.relative_to(self.home)) for p in group.items(self.home))
                for group in outputs.PARTS[part][1]}

    def test_each_part_offers_only_what_it_writes(self):
        self.assertEqual(self.offered("local"), {"database": ["LocalExtraction/local_output/database.xlsx",
                                                              "LocalExtraction/local_output/papers.csv"]})
        self.assertEqual(self.offered("web"), {
            "dois": ["WebScraping/Fetch_DOIs/dois.csv", "WebScraping/Fetch_DOIs/dois.txt"],
            "papers": ["WebScraping/papers/10.1_a.pdf", "WebScraping/papers/ledger.sqlite"],
            "database": ["WebScraping/web_output/papers.csv"]})
        self.assertEqual(self.offered("rank"), {"results": ["SelectingTopMaterial/results/report.html"]})
        self.assertEqual(self.offered("classify"), {"classes": ["Classification/all_materials.csv",
                                                                "Classification/crystal_structure"]})

    def test_deleting_keeps_the_inputs_and_the_folders(self):
        for part, (_, groups) in outputs.PARTS.items():
            self.assertEqual(outputs.delete([i for g in groups for i in g.items(self.home)]), [])
        self.assertTrue((self.home / "LocalExtraction/papers/mine.pdf").exists())
        self.assertTrue((self.home / "WebScraping/Fetch_DOIs/my notes.txt").exists())
        self.assertTrue((self.home / "SelectingTopMaterial/results/my notes.txt").exists())
        self.assertTrue((self.home / "configs/sse.yaml").exists())
        self.assertTrue((self.home / "LocalExtraction/local_output").is_dir())  # emptied, not removed
        self.assertEqual(list((self.home / "LocalExtraction/local_output").iterdir()), [])
        self.assertFalse((self.home / "Classification/crystal_structure").exists())

    def test_a_part_in_use_says_so(self):
        class Panel:
            def __init__(self):
                self.working = True

            def running(self):
                return self.working
        panel = Panel()
        outputs.register("web", panel.running, "a step is running", groups=("papers",))
        self.assertEqual(outputs.in_use("web", "papers"), "a step is running")
        self.assertIsNone(outputs.in_use("web", "database"))
        self.assertIsNone(outputs.in_use("local", "database"))
        panel.working = False
        self.assertIsNone(outputs.in_use("web", "papers"))
        panel.working = True
        del panel  # the window is gone: forgotten
        self.assertIsNone(outputs.in_use("web", "papers"))

    def test_sizes(self):
        self.assertEqual(outputs.size_of(outputs.PARTS["web"][1][1].items(self.home)), (2, 2))
        self.assertEqual(outputs.readable_size(2048), "2.0 KB")


def has_screen() -> bool:
    if tk is None or os.environ.get("MME_NO_WINDOW_TESTS"):
        return False
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(has_screen(), "the window needs a screen")
class DialogTests(ProjectFolder):
    def setUp(self):
        super().setUp()
        for name in ("askyesno", "showinfo", "showwarning"):
            patcher = mock.patch(f"tkinter.messagebox.{name}", return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def test_only_what_is_ticked_is_deleted(self):
        from LocalExtraction.gui.delete_outputs import DeleteOutputsDialog
        closed = []
        dialog = DeleteOutputsDialog(self.root, "web", home=self.home, on_close=closed.append)
        self.assertEqual(str(dialog.delete_button["state"]), "disabled")  # nothing ticked yet
        dialog.ticks["database"].set(True)
        dialog._update()
        self.assertTrue(dialog.delete())
        self.assertFalse((self.home / "WebScraping/web_output/papers.csv").exists())
        self.assertTrue((self.home / "WebScraping/Fetch_DOIs/dois.txt").exists())
        self.assertTrue((self.home / "WebScraping/papers/ledger.sqlite").exists())
        self.assertEqual(closed, [True])

    def test_a_no_to_the_question_deletes_nothing(self):
        from LocalExtraction.gui.delete_outputs import DeleteOutputsDialog
        dialog = DeleteOutputsDialog(self.root, "local", home=self.home)
        dialog.ticks["database"].set(True)
        with mock.patch("tkinter.messagebox.askyesno", return_value=False):
            self.assertFalse(dialog.delete())
        self.assertTrue((self.home / "LocalExtraction/local_output/papers.csv").exists())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
