# LocalExtraction/runcontrol.py
"""Pause / Resume, and the wait for the internet, for every long step of MoukhlijMatExtract.

Pause and Stop
  Each window gives its step a RunControl as its stop event — the same Event as before for Stop, with
  pause() / resume() on top — and binds it to the threads that work for the step (`bound`, `task`).
  Those threads look at it often: before every web request, during every wait between requests, every
  piece of a download and every page of a PDF (`check`). Paused, they hold there; stopped, they raise
  StepStopped there, so a step ends within moments — not after the papers under way are all done.
  A web request still waiting for its site when Stop is pressed is not waited for either.
  What a step had finished is kept; what it was in the middle of is done again by the next run.

The internet
  install() wraps every web request made with `requests`. When one fails and the computer has no
  internet, it says so once, waits until the connection is back (checked every 10 s), then sends the
  same request again — instead of the step taking every paper or DOI of the outage for "not found".
  When the internet is there, a failure is the site's: it is raised as before.
  `no_wait()` lets a lookup that can do without the internet (the metadata of local extraction)
  fail at once instead."""

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, List, Optional

_CHECK_EVERY = 10.0  # seconds between two checks of the connection while it is down
_PROBES = ("https://www.gstatic.com/generate_204", "https://1.1.1.1/", "https://www.baidu.com/")
WAITING = "No internet connection — waiting for it to come back (checked every 10 s) …"
BACK = "The internet connection is back — going on."

_log = logging.getLogger("MoukhlijMatExtract")


class RunControl(threading.Event):
    """The stop event of a step (set() = Stop), which can also be paused and resumed."""

    def __init__(self) -> None:
        super().__init__()
        self._running = threading.Event()
        self._running.set()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def clear(self) -> None:
        """A new run: not stopped, not paused."""
        super().clear()
        self.resume()

    def set(self) -> None:
        """Stop: a paused step is let go so that it can end."""
        super().set()
        self.resume()

    def hold(self) -> bool:
        """Waits while paused (not when stopped). True if it did wait."""
        waited = False
        while self.paused and not self.is_set():
            waited = True
            self._running.wait(0.5)  # short waits: a signal (Stop from the window) gets through
        return waited


class StepStopped(BaseException):
    """Stop was pressed: the step ends where it is. (A BaseException, like KeyboardInterrupt, so that the
    `except Exception` meant for a failing paper or source do not swallow it.)"""


_local = threading.local()  # the RunControl of the step this thread works for; no_wait


def _controls(control: Optional[threading.Event] = None) -> List[RunControl]:
    found: List[RunControl] = []
    for one in (control, getattr(_local, "control", None)):
        if isinstance(one, RunControl) and one not in found:
            found.append(one)
    return found


def checkpoint(control: Optional[threading.Event] = None) -> bool:
    """Waits here while the step is paused. True if it did wait."""
    waited = False
    for one in _controls(control):
        waited = one.hold() or waited
    return waited


def stopped(control: Optional[threading.Event] = None) -> bool:
    return any(one.is_set() for one in _controls(control))


def check(control: Optional[threading.Event] = None) -> None:
    """A point where the step may pause or end: waits while paused; raises StepStopped once stopped.
    Does nothing for work no window controls (a run from the terminal)."""
    checkpoint(control)
    if stopped(control):
        raise StepStopped()


def sleep(seconds: float) -> None:
    """time.sleep that a Pause holds and a Stop ends (StepStopped)."""
    end = time.monotonic() + seconds
    while True:
        check()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 0.2))


def current() -> Optional[threading.Event]:
    """The step this thread works for (to hand on to the threads it starts)."""
    return getattr(_local, "control", None)


@contextmanager
def bound(control: Optional[threading.Event]) -> Iterator[None]:
    """The work of this thread is for this step: its web requests pause with it, and stop waiting
    for the internet when it is stopped."""
    before = getattr(_local, "control", None)
    _local.control = control
    try:
        yield
    finally:
        _local.control = before


def task(control: Optional[threading.Event], function: Callable, *arguments):
    """A function to hand to a pool of worker threads: it waits while the step is paused, then runs
    `function(*arguments)` bound to the step — or raises StepStopped without starting, once stopped."""
    def run():
        with bound(control):
            check(control)
            return function(*arguments)
    return run


STOPPED_BY_CTRL_C = ("Stopped (Ctrl-C). What was finished is kept; run the same command again to go on "
                     "from where it stopped.")


# ---------------------------------------------------------------------------------------------------------------------
# Stopping from the terminal: every way a terminal stops a program, said in a box that cannot be missed
# ---------------------------------------------------------------------------------------------------------------------
_SIGNAL_WORDS = {"SIGINT": "Ctrl-C", "SIGTERM": "a stop signal (SIGTERM)", "SIGHUP": "the terminal was closed (SIGHUP)",
                 "SIGBREAK": "Ctrl-Break"}
_COLOURS = {"wait": "33", "done": "32", "quit": "31"}  # yellow, green, red


def stop_signals() -> List[int]:
    """The signals a terminal stops a program with, those this system has: Ctrl-C, kill (SIGTERM), the terminal
    closed (SIGHUP), Ctrl-Break (Windows)."""
    import signal
    return [getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK") if hasattr(signal, name)]


def signal_words(signum: int) -> str:
    import signal
    try:
        return _SIGNAL_WORDS.get(signal.Signals(signum).name, signal.Signals(signum).name)
    except ValueError:
        return f"signal {signum}"


def stop_box(kind: str, cause: str = "", what: str = "MoukhlijMatExtract") -> str:
    """The box said when a run is stopped from the terminal. `kind`: "wait" (stopping: please wait), "done"
    (stopped cleanly) or "quit" (quitting at once). Coloured when the terminal shows colours (not with NO_COLOR)."""
    if kind == "wait":
        title = f"⏳  Stop requested{f' — {cause}' if cause else ''}"
        lines = [f"Please wait: {what} is saving its work and finishing peacefully.",
                 "What is finished is kept; the same command goes on from there next time.",
                 "", "Press Ctrl-C again only to quit at once (the item under way is lost)."]
    elif kind == "done":
        title = "✓  Stopped cleanly"
        lines = ["Everything finished is saved.", "Run the same command again to go on where it stopped."]
    else:
        title = "✗  Quitting at once"
        lines = ["What was already saved is kept; the item under way is not.",
                 "Run the same command again to go on."]
    body = [title, ""] + lines
    width = max(_columns(line) for line in body) + 4
    box = (["╭" + "─" * width + "╮"] + [f"│  {line}{' ' * (width - 4 - _columns(line))}  │" for line in body]
           + ["╰" + "─" * width + "╯"])
    text = "\n" + "\n".join(box) + "\n"
    try:
        import sys
        colour = sys.stderr.isatty() and not os.environ.get("NO_COLOR")
    except Exception:
        colour = False
    return f"\033[{_COLOURS[kind]}m{text}\033[0m" if colour else text


def _columns(text: str) -> int:
    """How many columns a line takes in a terminal: wide characters (⏳, CJK) take two."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def say_box(kind: str, cause: str = "", what: str = "MoukhlijMatExtract") -> None:
    """Writes the box to the terminal. os.write, not print: safe inside a signal handler; a closed terminal
    (SIGHUP) is not an error."""
    try:
        os.write(2, stop_box(kind, cause, what).encode("utf-8", "replace"))
    except OSError:
        pass


def _install(handler, signals: List[int]) -> dict:
    import signal
    before = {}
    for sig in signals:
        try:
            before[sig] = signal.signal(sig, handler)
        except (ValueError, OSError):  # not the main thread, or not allowed here: that signal keeps its meaning
            pass
    return before


def _restore(before: dict) -> None:
    import signal
    for sig, handler in before.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError, TypeError):
            pass


# The steps the windows run, for a stop signal (Ctrl-C in the terminal the window was started from): each window
# registers (is a step running?, stop it), and the signal stops them as Stop does before the windows close.
_running_steps: List[tuple] = []
_steps_lock = threading.Lock()


def register_step(busy: Callable[[], bool], stop: Callable[[], None]) -> Callable[[], None]:
    """A window's running step, for stop signals. Returns the function that forgets it (the window closed)."""
    entry = (busy, stop)
    with _steps_lock:
        _running_steps.append(entry)

    def forget() -> None:
        with _steps_lock:
            if entry in _running_steps:
                _running_steps.remove(entry)
    return forget


def busy_steps() -> List[tuple]:
    """The registered steps running now."""
    with _steps_lock:
        steps = list(_running_steps)
    running = []
    for busy, stop in steps:
        try:
            if busy():
                running.append((busy, stop))
        except Exception:  # a window half closed: not a step
            pass
    return running


@contextmanager
def ctrl_c_stops(what: str = "MoukhlijMatExtract") -> Iterator[RunControl]:
    """For a step run from the terminal: the first stop signal (Ctrl-C, kill, the terminal closed, Ctrl-Break)
    stops it as Stop does in the window — the work under way is left off, what was finished is kept and saved, so
    the same command goes on from there — with a box saying to wait; a box says when it has stopped cleanly. A
    second signal quits at once. Yields the step's RunControl (its stop event)."""
    control = RunControl()
    asked = []

    def on_signal(signum, frame) -> None:
        if control.is_set():
            asked.append("quit")
            say_box("quit")
            raise KeyboardInterrupt
        control.set()
        asked.append(signum)
        say_box("wait", signal_words(signum), what)

    before = _install(on_signal, stop_signals())
    try:
        with bound(control):
            yield control
    finally:
        _restore(before)
        if asked and "quit" not in asked:  # “stopped cleanly” only when it was: not after “quitting at once”
            say_box("done")


@contextmanager
def finish_then_stop(what: str = "MoukhlijMatExtract") -> Iterator[None]:
    """For a short command (a ranking, a classification, a release: seconds): a stop signal does not cut it in the
    middle of writing its files. It says to wait, the command finishes and saves, then says it stopped. A second
    signal quits at once."""
    asked = []

    def on_signal(signum, frame) -> None:
        if asked:
            asked.append("quit")
            say_box("quit")
            raise KeyboardInterrupt
        asked.append(signum)
        say_box("wait", signal_words(signum), what)

    before = _install(on_signal, stop_signals())
    try:
        yield
    finally:
        _restore(before)
        if asked and "quit" not in asked:
            say_box("done")


@contextmanager
def no_wait() -> Iterator[None]:
    """Web requests made here fail at once when the internet is down (no waiting)."""
    before = getattr(_local, "no_wait", False)
    _local.no_wait = True
    try:
        yield
    finally:
        _local.no_wait = before


# ----------------------------------------------------------------------
# The internet
# ----------------------------------------------------------------------
_wait_lock = threading.Lock()
_offline = threading.Event()  # set while some thread has found the connection down
_listeners: List[Callable[[bool], None]] = []


def on_connection(listener: Callable[[bool], None]) -> None:
    """`listener(False)` when the connection is found down, `listener(True)` when it is back."""
    _listeners.append(listener)


def off_connection(listener: Callable[[bool], None]) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def _tell(online_now: bool) -> None:
    message = BACK if online_now else WAITING
    if logging.getLogger().handlers:
        (_log.info if online_now else _log.warning)(message)
    else:  # a run in a terminal without logging set up
        print(f"\n\t{message}", flush=True)
    for listener in list(_listeners):
        try:
            listener(online_now)
        except Exception:
            pass


def online() -> bool:
    """Does the computer reach the internet? (any answer of a few big sites, through the same proxy
    settings as the real requests)."""
    import requests
    before = getattr(_local, "probing", False)
    _local.probing = True
    try:
        with requests.Session() as session:
            for url in _PROBES:
                try:
                    session.head(url, timeout=5, allow_redirects=False)
                    return True
                except requests.RequestException:
                    continue
        return False
    finally:
        _local.probing = before


def wait_for_internet(control: Optional[threading.Event] = None) -> bool:
    """Called when a request failed and the internet looked gone: says so (once, whatever the number
    of threads waiting), waits until it is back and says that too. False if the step was stopped meanwhile."""
    while not _wait_lock.acquire(timeout=0.5):  # one thread checks; the others wait for its answer
        if stopped(control):
            return False
    try:
        if not _offline.is_set():
            if online():  # another thread's wait has just ended
                return not stopped(control)
            _offline.set()
            _tell(False)
        while not online():
            deadline = time.monotonic() + _CHECK_EVERY
            while time.monotonic() < deadline:
                if stopped(control):
                    return False
                time.sleep(0.2)
        _offline.clear()
        _tell(True)
    finally:
        _wait_lock.release()
    return not stopped(control)


_installed = False


def _send_until_stopped(original: Callable, session, request, kwargs) -> object:
    """Sends a request for a step a window controls, so that Stop does not wait for a slow site:
    the request runs on a helper thread, and once Stop is pressed it is left to end on its own
    (its answer is thrown away) while the step raises StepStopped at once. Outside a step (a run
    from the terminal) the request is sent as it is."""
    control = current()
    if not isinstance(control, RunControl):
        return original(session, request, **kwargs)
    lock, finished = threading.Lock(), threading.Event()
    box: dict = {"abandoned": False}
    no_wait_here = getattr(_local, "no_wait", False)

    def run() -> None:
        _local.control, _local.no_wait = control, no_wait_here  # a redirect is sent as the step's own request
        try:
            result, error = original(session, request, **kwargs), None
        except BaseException as caught:  # handed to the step's thread below
            result, error = None, caught
        with lock:
            if box["abandoned"]:  # Stop came first: nobody reads this answer
                if result is not None:
                    result.close()
                return
            box["result"], box["error"] = result, error
            finished.set()

    threading.Thread(target=run, daemon=True, name="request").start()
    while not finished.wait(0.2):
        if control.is_set():
            with lock:
                if not finished.is_set():
                    box["abandoned"] = True
                    raise StepStopped()
    if box["error"] is not None:
        raise box["error"]
    return box["result"]


def install() -> None:
    """Every web request of this program pauses with its step and waits for the internet."""
    global _installed
    if _installed or os.environ.get("MME_NO_NET_WAIT"):
        return
    import requests
    original = requests.Session.send

    def send(self, request, **kwargs):
        if getattr(_local, "probing", False):
            return original(self, request, **kwargs)
        while True:
            paused = checkpoint()
            if stopped():
                raise StepStopped()  # Stop was pressed: no new request for this step
            try:
                return _send_until_stopped(original, self, request, kwargs)
            except (requests.ConnectionError, requests.Timeout):
                if getattr(_local, "no_wait", False):
                    raise
                if not _offline.is_set() and online():
                    if paused:  # a kept-alive connection the site closed during the pause
                        paused = False
                        try:
                            return _send_until_stopped(original, self, request, kwargs)
                        except (requests.ConnectionError, requests.Timeout):
                            pass
                    raise  # the internet is there: the site did not answer
                if not wait_for_internet():
                    raise StepStopped() from None  # Stop was pressed while it waited

    send.__wrapped__ = original  # type: ignore[attr-defined]
    requests.Session.send = send
    _installed = True


# ---------------------------------------------------------------------------
# Keeping the computer awake while a long step runs
# ---------------------------------------------------------------------------
_awake_lock = threading.Lock()
_awake_count = 0
_awake_helper = None  # the process that holds the computer awake (macOS, Linux)


@contextmanager
def stay_awake(why: str = "a step of MoukhlijMatExtract is running") -> Iterator[None]:
    """Keeps the computer from going to sleep while idle for as long as the block runs: a download of
    thousands of papers or a long extraction would otherwise stop each time it sleeps. The screen may
    still turn off. macOS: caffeinate; Windows: SetThreadExecutionState; Linux: systemd-inhibit. Where
    none is available, nothing changes. Nested blocks share one hold."""
    global _awake_count, _awake_helper
    windows = os.name == "nt"
    with _awake_lock:
        _awake_count += 1
        if _awake_count == 1 and not windows:
            _awake_helper = _start_awake_helper(why)
    if windows:
        _windows_awake(True)
    try:
        yield
    finally:
        if windows:
            _windows_awake(False)
        with _awake_lock:
            _awake_count -= 1
            if _awake_count == 0 and _awake_helper is not None:
                try:
                    _awake_helper.terminate()
                    _awake_helper.wait(timeout=5)
                except Exception:  # it ends with this program anyway
                    pass
                _awake_helper = None


def _start_awake_helper(why: str):
    import shutil
    import subprocess
    import sys
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        command = ["caffeinate", "-i", "-w", str(os.getpid())]  # ends by itself if this program ends
    elif shutil.which("systemd-inhibit"):
        from .keep_awake import until_gone  # the lock ends with this program, killed or not
        command = ["systemd-inhibit", "--what=idle:sleep", "--who=MoukhlijMatExtract", f"--why={why}",
                   "--mode=block", *until_gone(os.getpid())]
    else:
        return None
    try:
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except OSError:
        logging.debug("Could not keep the computer awake", exc_info=True)
        return None


def _windows_awake(on: bool) -> None:
    try:
        import ctypes
        continuous, system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(continuous | (system_required if on else 0))
    except Exception:
        logging.debug("Could not keep the computer awake", exc_info=True)
