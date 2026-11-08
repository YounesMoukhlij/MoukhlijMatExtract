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


@contextmanager
def ctrl_c_stops() -> Iterator[RunControl]:
    """For a step run from the terminal: the first Ctrl-C stops it as Stop does in the window — the
    work under way is left off, what was finished is kept and saved, so the same command goes on
    from there — and a second Ctrl-C quits at once. Yields the step's RunControl (its stop event)."""
    control = RunControl()

    def on_ctrl_c(signum, frame) -> None:
        if control.is_set():
            raise KeyboardInterrupt
        control.set()
        # os.write, not print: a signal handler must not take the lock of sys.stdout
        os.write(2, b"\nStopping (Ctrl-C): what is under way is left off, what was finished is saved. "
                    b"Press Ctrl-C again to quit at once.\n")

    import signal
    try:
        before = signal.signal(signal.SIGINT, on_ctrl_c)
    except ValueError:  # not the main thread: Ctrl-C keeps its usual meaning
        before = None
    try:
        with bound(control):
            yield control
    finally:
        if before is not None:
            signal.signal(signal.SIGINT, before)


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
