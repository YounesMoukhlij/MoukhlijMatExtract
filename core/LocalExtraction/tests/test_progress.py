# LocalExtraction/tests/test_progress.py
"""How far a long step is: the estimate when it starts (from the pace of the earlier runs, or a first guess said to
be one), the line of the window (what, how many of how many, the counters, the time left and when it will be done),
the phases ticked off, the timeline of what was done when, the pace kept for the next estimate; and the details
window that follows a step (its tiles, phases, timeline, Pause and Stop, the timeline saved as CSV).

The window tests need a screen; without one they are skipped."""

import csv
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from LocalExtraction.gui import progress
from LocalExtraction.gui.progress import Timings, Tracker
from LocalExtraction.tests.test_gui import has_screen

PHASES = [("keywords", "Searching the keywords", "searches"), ("records", "Completing the records", "papers"),
          ("screen", "Scoring the papers", "papers")]


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.timings = Timings(self.base / "timings.json")

    def tracker(self, phases=PHASES):
        return Tracker("web", "Web scraping · 2 · Search", phases, timings=self.timings)

    def test_before_any_run_the_estimate_is_a_first_guess_and_says_so(self):
        t = self.tracker()
        t.start({"keywords": 100})
        self.assertAlmostEqual(t.estimate, 100 * progress.FIRST_GUESS["keywords"])
        self.assertFalse(t.estimate_measured)
        self.assertIn("a first guess", t.start_text("Searching"))
        self.assertIn("done around", t.start_text("Searching"))

    def test_a_finished_run_makes_the_next_estimate_from_its_pace(self):
        t = self.tracker([("keywords", "Searching the keywords", "searches")])
        t.start({"keywords": 10})
        t.update("keywords", 1, 10)
        t.phases["keywords"].started -= 40  # forty seconds for the ten searches (the clock began with the step)
        t.update("keywords", 10, 10)
        t.finish("done")
        pace, measured = Timings(self.base / "timings.json").seconds("keywords")  # read back from the file
        self.assertTrue(measured)
        self.assertAlmostEqual(pace, 40 / 10, delta=0.2)  # every search timed, the first one too
        nxt = self.tracker([("keywords", "Searching the keywords", "searches")])
        nxt.start({"keywords": 20})
        self.assertTrue(nxt.estimate_measured)
        self.assertIn("from your earlier runs", nxt.start_text("Searching"))

    def test_a_stopped_run_does_not_teach_a_wrong_pace(self):
        t = self.tracker([("keywords", "Searching the keywords", "searches")])
        t.start({"keywords": 10})
        t.update("keywords", 3, 10)
        t.finish("stopped")
        self.assertFalse(Timings(self.base / "timings.json").seconds("keywords")[1])

    def test_the_line_says_what_how_many_the_counters_and_the_time_left(self):
        t = self.tracker()
        t.start({"keywords": 2128})
        t.update("keywords", 148, 2128, "OpenAlex: “LLZO garnet”", {"new papers": 312})
        line = t.line()
        self.assertTrue(line.startswith("Searching the keywords — 148 of 2,128 searches · OpenAlex: “LLZO garnet”"))
        self.assertIn("new papers: 312", line)
        self.assertIn("left · done around", line)

    def test_phases_are_ticked_off_in_order_and_the_timeline_says_what_was_done_when(self):
        t = self.tracker()
        t.start({"keywords": 2})
        t.update("keywords", 1, 2, "OpenAlex: “garnet”")
        t.update("keywords", 2, 2, "Crossref: “garnet”")
        t.update("screen", 10, 50)  # the records were skipped (nothing to complete)
        self.assertEqual(t.phases["keywords"].state(), "done")
        self.assertEqual(t.phases["records"].state(), "next")
        self.assertEqual(t.phases["screen"].state(), "now")
        texts = [e.text for e in t.events]
        self.assertTrue(any("OpenAlex: “garnet”" in x for x in texts))
        self.assertTrue(any("Scoring the papers started" == x for x in texts))
        t.finish("done")
        self.assertTrue(t.events[-1].text.startswith("Finished after"))
        rows = t.rows()
        self.assertEqual(set(rows[0]), {"time", "phase", "what"})

    def test_the_time_left_and_how_far_follow_the_pace(self):
        t = self.tracker([("keywords", "Searching the keywords", "searches")])
        t.start({"keywords": 100})
        t.update("keywords", 1, 100)
        t.phases["keywords"].started -= 10
        t.started -= 10  # the step began ten seconds ago too
        t.update("keywords", 10, 100)  # ten searches in ten seconds: one a second
        self.assertAlmostEqual(t.left(), 90, delta=3)
        self.assertGreater(t.fraction(), 0.05)
        self.assertEqual(t.pace_text(), "1.0 s per search")

    def test_a_step_started_again_goes_on_from_what_an_earlier_run_finished(self):
        # 78 of 100 searches answered before the window was quit: the bar starts at 78, the estimate counts the 22
        # left, and the pace is measured on the searches this run asks, never on the 78 it skips.
        t = self.tracker([("keywords", "Searching the keywords", "searches")])
        t.start({"keywords": 100}, before={"keywords": 78})
        self.assertEqual(t.phases["keywords"].done, 78)
        self.assertAlmostEqual(t.estimate, 22 * progress.FIRST_GUESS["keywords"])
        t.update("keywords", 78, 100, "skipped")
        t.phases["keywords"].started -= 10
        t.started -= 10
        t.update("keywords", 83, 100)  # five searches asked in ten seconds: 2 s each
        self.assertEqual(t.pace_text(), "2.0 s per search")
        self.assertAlmostEqual(t.left(), 17 * 2, delta=3)
        self.assertIn("83 of 100 searches", t.line())
        t.update("keywords", 100, 100)
        t.finish("done")
        pace, _ = Timings(self.base / "timings.json").seconds("keywords")
        self.assertGreater(pace, 0.4)  # 22 searches timed (about 0.5 s each here), not 100

    def test_how_far_counts_work_never_goes_back_and_is_the_same_for_every_reader(self):
        t = self.tracker()
        t.start({"keywords": 100}, before={"keywords": 78})
        self.assertAlmostEqual(t.fraction(), 0.78, delta=0.01)  # a resumed step starts where it was
        t.update("keywords", 90, 100)
        first = t.fraction()
        self.assertAlmostEqual(first, 0.90, delta=0.01)  # one phase known: its own share of the work
        self.assertEqual(t.fraction(), first)  # read again later (the details window, every half second): unchanged
        t.update("records", 1, 500)  # a phase whose size is known only now: more work, the number waits
        self.assertGreaterEqual(t.fraction(), first)
        t.finish("stopped")
        self.assertGreaterEqual(t.fraction(), first)  # stopped: where it was, not 100 %
        done = self.tracker()
        done.start({"keywords": 10})
        done.update("keywords", 10, 10)
        done.finish("done")
        self.assertEqual(done.fraction(), 1.0)

    def test_a_listener_that_fails_is_let_go(self):
        t = self.tracker()
        t.listeners.append(mock.Mock(side_effect=RuntimeError("gone")))
        t.start({"keywords": 1})
        self.assertEqual(t.listeners, [])

    def test_long_times_are_said_in_hours_then_days(self):
        from LocalExtraction.gui.progress_text import duration
        for seconds, said in ((3, "3 s"), (47, "45 s"), (26 * 60, "26 min"), (59 * 60 + 40, "1 h"), (80 * 60, "1 h 20 min"),
                              (10 * 3600 + 20 * 60, "10 h"), (23 * 3600 + 40 * 60, "1 day"),
                              (26 * 3600, "1 day 2 h"), (49 * 3600 + 10 * 60, "2 days 1 h"),
                              (9 * 86400 + 5 * 3600, "9 days")):
            self.assertEqual(duration(seconds), said, seconds)
        t = self.tracker([("keywords", "Searching the keywords", "searches")])
        t.timings.data["keywords"] = {"seconds_per_item": 60.0}  # a minute a search, 3,000 searches: two days
        t.start({"keywords": 3000})
        self.assertIn("estimated 2 days 2 h", t.start_text("Searching"))

    def test_what_stopping_keeps_is_said_only_for_a_step_that_keeps_it(self):
        t = Tracker("web", "Web scraping · 1 · Fetch DOIs", [("dois", "Fetch DOIs", "searches")],
                    timings=self.timings, saved_on_stop="every DOI found so far is saved in the DOI list")
        self.assertEqual(t.stop_text(), "✓ If you stop now, every DOI found so far is saved in the DOI list.")
        self.assertEqual(self.tracker().stop_text(), "")  # a step that cannot be stopped half-way says nothing

    def test_one_of_a_unit(self):
        for many, one in (("searches", "search"), ("papers kept", "paper kept"), ("PDFs", "PDF"),
                          ("compositions", "composition"), ("boxes", "box"), ("", "")):
            self.assertEqual(progress.singular(many), one)

    def test_the_clock(self):
        self.assertRegex(progress.clock(time.time()), r"^\d\d:\d\d$")
        self.assertRegex(progress.clock(time.time() + 3 * 86400), r"^\w{3} \d\d:\d\d$")


@unittest.skipUnless(has_screen(), "the window needs a screen")
class DetailsWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)
        self.paused = False
        self.calls = []
        self.tracker = Tracker("web", "Web scraping · 2 · Search", PHASES, timings=Timings(self.base / "t.json"),
                               controls={"pause": lambda: self.calls.append("pause"),
                                         "stop": lambda: self.calls.append("stop"), "paused": lambda: self.paused})
        self.tracker.start({"keywords": 4})
        self.tracker.update("keywords", 1, 4, "OpenAlex: “garnet”", {"new papers": 3})

    def window(self):
        win = progress.open_details(self.root, self.tracker, "Web scraping")
        win.attributes("-alpha", 0.0)
        win.refresh()
        return win

    def test_it_shows_the_step_its_phases_and_its_timeline(self):
        win = self.window()
        self.assertEqual(win.tiles["State"].cget("text"), "Running")
        self.assertNotEqual(win.tiles["Started"].cget("text"), "–")
        mark, name, bar, count = win._phase_rows["keywords"]
        self.assertEqual(mark.cget("text"), "▶")
        self.assertIn("1 of 4 searches", count.cget("text"))
        self.assertEqual(win._phase_rows["screen"][0].cget("text"), "○")
        self.assertIn("OpenAlex: “garnet”", win.now.cget("text"))
        self.assertIn("new papers: 3", win.counters.cget("text"))
        whats = [win.timeline.item(i, "values")[2] for i in win.timeline.get_children()]
        self.assertTrue(any("OpenAlex: “garnet”" in w for w in whats))

    def test_the_timeline_keeps_up_with_a_long_step(self):
        # The tracker keeps the last 2,000 events; a resumed search says thousands in its first seconds. The timeline
        # went on showing the 2,000th as the newest, forever: it must show the newest, and keep at most 2,000 rows.
        win = self.window()
        for n in range(2500):
            self.tracker.event("keywords", f"search {n}")
        win.refresh()
        rows = win.timeline.get_children()
        self.assertEqual(win.timeline.item(rows[0], "values")[2], "search 2499")
        self.assertLessEqual(len(rows), 2000)
        self.tracker.event("keywords", "one more")
        win.refresh()
        self.assertEqual(win.timeline.item(win.timeline.get_children()[0], "values")[2], "one more")

    def test_pause_and_stop_reach_the_step(self):
        win = self.window()
        win.pause_button.invoke()
        win.stop_button.invoke()
        self.assertEqual(self.calls, ["pause", "stop"])
        self.paused = True
        win.refresh()
        self.assertEqual(win.tiles["State"].cget("text"), "Paused")
        self.assertEqual(win.pause_button.cget("text"), "Resume")

    def test_once_ended_it_says_how_it_ended_and_the_buttons_rest(self):
        self.tracker.finish("stopped")
        win = self.window()
        self.assertEqual(win.tiles["State"].cget("text"), "Stopped")
        self.assertEqual(str(win.stop_button.cget("state")), "disabled")

    def test_asked_again_it_comes_back_on_the_step_of_now(self):
        win = self.window()
        newer = Tracker("web", "Web scraping · 3 · Download", [("download", "Downloading", "papers")],
                        timings=Timings(self.base / "t.json"))
        newer.start({"download": 9})
        again = progress.open_details(self.root, newer, "Web scraping")
        self.assertIs(again, win)
        self.assertIs(win.tracker, newer)
        self.assertEqual(list(win._phase_rows), ["download"])

    def test_the_timeline_is_saved_as_csv(self):
        win = self.window()
        path = self.base / "timeline.csv"
        with mock.patch("tkinter.filedialog.asksaveasfilename", return_value=str(path)):
            win._save()
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        self.assertTrue(any("OpenAlex" in r["what"] for r in rows))

    def test_the_button_says_when_nothing_has_run_yet(self):
        import tkinter as tk
        holder = tk.Frame(self.root)
        button = progress.details_button(holder, lambda: None, "Ranking")
        with mock.patch("tkinter.messagebox.showinfo") as said:
            button.invoke()
        self.assertIn("No step has run", said.call_args[0][1])

    def test_the_stop_note_shows_while_the_step_runs(self):
        import tkinter as tk
        holder = tk.Frame(self.root)
        holder.pack()
        self.tracker.saved_on_stop = "every DOI found so far is saved"
        note = progress.stop_note(holder)
        progress.show_stop_note(note, self.tracker, True, fill="x")
        self.assertTrue(note.winfo_manager())
        self.assertIn("If you stop now, every DOI found so far is saved", note.cget("text"))
        win = self.window()
        self.assertIn("If you stop now", win.saved.cget("text"))  # in the details window too
        progress.show_stop_note(note, self.tracker, False)
        self.assertFalse(note.winfo_manager())
        self.tracker.finish("stopped")
        win.refresh()
        self.assertEqual(win.saved.cget("text"), "")  # ended: nothing to stop any more

    def test_the_line_is_dark_yellow_while_it_runs(self):
        import tkinter as tk
        label = tk.Label(self.root, text="x", foreground="#222222")
        progress.style_running(label, True)
        self.assertEqual(str(label.cget("foreground")), progress.gold(self.root))
        progress.style_running(label, False, rest="#222222")
        self.assertEqual(str(label.cget("foreground")), "#222222")
