# LocalExtraction/tests/test_fileurls.py
"""Links to the files of this computer, right on macOS, Linux and Windows: made as file:///… (a Windows drive as
/C:/…), read back to the path; the links of older versions (“file://C:\\…”, a space not encoded) read too."""

import os
import tempfile
import unittest
from pathlib import Path

from LocalExtraction.fileurls import file_url, path_from_url


class FileUrlTests(unittest.TestCase):
    def test_a_link_made_here_leads_back_to_the_file(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        pdf = folder / "a paper — é.pdf"
        pdf.write_bytes(b"%PDF")
        url = file_url(pdf)
        self.assertTrue(url.startswith("file:///"))
        self.assertNotIn(" ", url)  # encoded, as a URL is
        self.assertTrue(os.path.samefile(path_from_url(url), pdf))

    def test_windows_links(self):
        self.assertEqual(path_from_url("file:///C:/Users/me/My%20papers/a.pdf", windows=True),
                         r"C:\Users\me\My papers\a.pdf")
        self.assertEqual(path_from_url(r"file://C:\Users\me\a.pdf", windows=True), r"C:\Users\me\a.pdf")  # older
        self.assertEqual(path_from_url("file://server/share/a.pdf", windows=True), r"\\server\share\a.pdf")

    def test_macos_and_linux_links(self):
        self.assertEqual(path_from_url("file:///Users/me/a%20b.pdf", windows=False), "/Users/me/a b.pdf")
        self.assertEqual(path_from_url("file:///Users/me/a b.pdf", windows=False), "/Users/me/a b.pdf")  # older
        self.assertEqual(path_from_url("file://localhost/home/me/a.pdf", windows=False), "/home/me/a.pdf")

    def test_other_links_are_not_files(self):
        for url in ("https://example.org/a.pdf", "", None, "ftp://x/a.pdf"):
            self.assertEqual(path_from_url(url), "")


if __name__ == "__main__":
    unittest.main()
