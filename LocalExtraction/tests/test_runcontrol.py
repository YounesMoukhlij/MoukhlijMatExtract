"""Pause / Resume and the wait for the internet (LocalExtraction/runcontrol.py)."""

import io
import threading
import time

import pytest
import requests
from requests.adapters import BaseAdapter

from LocalExtraction import runcontrol


# ----------------------------------------------------------------------
# Pause
# ----------------------------------------------------------------------
def test_a_paused_task_waits_until_resumed():
    control = runcontrol.RunControl()
    control.pause()
    ran = threading.Event()
    worker = threading.Thread(target=runcontrol.task(control, ran.set))
    worker.start()
    time.sleep(0.3)
    assert not ran.is_set()  # held while paused
    control.resume()
    worker.join(2)
    assert ran.is_set()


def test_stop_lets_a_paused_step_go():
    control = runcontrol.RunControl()
    control.pause()
    done = threading.Event()
    worker = threading.Thread(target=lambda: (runcontrol.checkpoint(control), done.set()))
    worker.start()
    control.set()  # Stop
    worker.join(2)
    assert done.is_set() and control.is_set() and not control.paused


def test_a_new_run_is_neither_stopped_nor_paused():
    control = runcontrol.RunControl()
    control.pause()
    control.set()
    control.clear()
    assert not control.is_set() and not control.paused
    assert runcontrol.checkpoint(control) is False  # nothing to wait for


# ----------------------------------------------------------------------
# The internet
# ----------------------------------------------------------------------
class _Flaky(BaseAdapter):
    """Fails with a connection error `failures` times, then answers 200."""

    def __init__(self, failures):
        super().__init__()
        self.failures, self.calls = failures, 0

    def send(self, request, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise requests.ConnectionError("network is unreachable")
        response = requests.Response()
        response.status_code, response.request, response.url = 200, request, request.url
        response.raw = io.BytesIO(b"ok")
        return response

    def close(self):
        pass


@pytest.fixture
def installed(monkeypatch):
    monkeypatch.delenv("MME_NO_NET_WAIT", raising=False)
    monkeypatch.setattr(runcontrol, "_installed", False)
    monkeypatch.setattr(runcontrol, "_CHECK_EVERY", 0.1)
    monkeypatch.setattr(runcontrol, "_offline", threading.Event())
    told = []
    monkeypatch.setattr(runcontrol, "_tell", told.append)
    original = requests.Session.send
    runcontrol.install()
    yield told
    requests.Session.send = original


def _session(adapter):
    session = requests.Session()
    session.mount("https://", adapter)
    return session


def test_waits_for_the_internet_then_sends_the_same_request_again(installed, monkeypatch):
    answers = iter([False, False, True])  # down, still down, back
    monkeypatch.setattr(runcontrol, "online", lambda: next(answers, True))
    adapter = _Flaky(failures=1)
    response = _session(adapter).get("https://example.org/paper.pdf")
    assert response.status_code == 200 and adapter.calls == 2
    assert installed == [False, True]  # "no internet" said once, then "back"


def test_a_site_that_fails_while_online_fails_as_before(installed, monkeypatch):
    monkeypatch.setattr(runcontrol, "online", lambda: True)
    adapter = _Flaky(failures=5)
    with pytest.raises(requests.ConnectionError):
        _session(adapter).get("https://example.org/down")
    assert adapter.calls == 1 and installed == []


def test_no_wait_fails_at_once(installed, monkeypatch):
    monkeypatch.setattr(runcontrol, "online", lambda: False)
    with runcontrol.no_wait(), pytest.raises(requests.ConnectionError):
        _session(_Flaky(failures=5)).get("https://example.org/x")
    assert installed == []


def test_stop_ends_the_wait(installed, monkeypatch):
    monkeypatch.setattr(runcontrol, "online", lambda: False)
    control = runcontrol.RunControl()
    threading.Timer(0.3, control.set).start()
    with runcontrol.bound(control), pytest.raises(runcontrol.StepStopped):  # the step ends, nothing marked failed
        _session(_Flaky(failures=5)).get("https://example.org/x")


def test_after_a_pause_a_closed_connection_is_tried_once_more(installed, monkeypatch):
    monkeypatch.setattr(runcontrol, "online", lambda: True)
    control = runcontrol.RunControl()
    control.pause()
    threading.Timer(0.3, control.resume).start()
    adapter = _Flaky(failures=1)  # the kept-alive connection the site closed during the pause
    with runcontrol.bound(control):
        assert _session(adapter).get("https://example.org/x").status_code == 200
    assert adapter.calls == 2


# ----------------------------------------------------------------------
# Stop ends a step where it is
# ----------------------------------------------------------------------
def test_a_stopped_step_sends_no_new_request(installed):
    control = runcontrol.RunControl()
    control.set()
    adapter = _Flaky(failures=0)
    with runcontrol.bound(control), pytest.raises(runcontrol.StepStopped):
        _session(adapter).get("https://example.org/x")
    assert adapter.calls == 0


def test_a_wait_between_requests_ends_on_stop_and_holds_on_pause():
    control = runcontrol.RunControl()
    threading.Timer(0.3, control.set).start()
    started = time.monotonic()
    with runcontrol.bound(control), pytest.raises(runcontrol.StepStopped):
        runcontrol.sleep(30)  # a 30 s wait (a site's crawl delay, a back-off) cut short by Stop
    assert time.monotonic() - started < 2
    control.clear()
    control.pause()
    threading.Timer(0.6, control.resume).start()
    started = time.monotonic()
    with runcontrol.bound(control):
        runcontrol.sleep(0.1)  # held while paused
    assert time.monotonic() - started >= 0.5


def test_queued_work_does_not_start_once_stopped():
    control = runcontrol.RunControl()
    control.set()
    ran = []
    with pytest.raises(runcontrol.StepStopped):
        runcontrol.task(control, ran.append, 1)()
    assert ran == []


def test_without_a_window_nothing_stops():
    runcontrol.check()  # a run from the terminal: no control, no effect
    runcontrol.sleep(0.01)


# ----------------------------------------------------------------------
# Stop does not wait for a slow site
# ----------------------------------------------------------------------
class _Slow(BaseAdapter):
    """Answers 200 after `seconds` (a site that keeps the request waiting)."""

    def __init__(self, seconds):
        super().__init__()
        self.seconds = seconds

    def send(self, request, **kwargs):
        time.sleep(self.seconds)
        response = requests.Response()
        response.status_code, response.request, response.url = 200, request, request.url
        response.raw = io.BytesIO(b"ok")
        return response

    def close(self):
        pass


def _stopped_after(control, seconds, work):
    """Runs `work` bound to `control`, presses Stop after `seconds`; how long it then took to end, and how."""
    ended = {}

    def run():
        with runcontrol.bound(control):
            try:
                work()
                ended["how"] = "returned"
            except runcontrol.StepStopped:
                ended["how"] = "stopped"
    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(seconds)
    pressed = time.monotonic()
    control.set()
    worker.join(10)
    return time.monotonic() - pressed, ended.get("how")


def test_stop_does_not_wait_for_a_request_a_slow_site_holds(installed):
    took, how = _stopped_after(runcontrol.RunControl(), 0.3,
                               lambda: _session(_Slow(5)).get("https://example.org/paper.pdf"))
    assert how == "stopped" and took < 1


def test_a_request_that_is_not_stopped_gives_its_answer(installed):
    with runcontrol.bound(runcontrol.RunControl()):
        response = _session(_Slow(0.3)).get("https://example.org/paper.pdf")
    assert response.status_code == 200 and response.content == b"ok"


def test_a_request_error_reaches_the_step(installed, monkeypatch):
    monkeypatch.setattr(runcontrol, "online", lambda: True)  # the site's fault, not the connection's
    with runcontrol.bound(runcontrol.RunControl()), pytest.raises(requests.ConnectionError):
        _session(_Flaky(failures=5)).get("https://example.org/paper.pdf")


def test_stop_ends_a_rate_limit_wait_of_fetch_dois(monkeypatch):
    from WebScraping.Fetch_DOIs import get_dois
    busy = requests.Response()
    busy.status_code, busy.headers["Retry-After"], busy.raw = 429, "60", io.BytesIO(b"")
    monkeypatch.setattr(get_dois.SESSION, "get", lambda *a, **k: busy)
    took, how = _stopped_after(runcontrol.RunControl(), 0.3, lambda: get_dois.get("https://api.example.org/works"))
    assert how == "stopped" and took < 1


def test_ctrl_c_in_the_terminal_stops_the_step_as_stop_does():
    import os
    import signal
    with runcontrol.ctrl_c_stops() as control:
        assert runcontrol.current() is control
        os.kill(os.getpid(), signal.SIGINT)  # the first Ctrl-C
        time.sleep(0.1)
        assert control.is_set()
        with pytest.raises(runcontrol.StepStopped):
            runcontrol.check()
        with pytest.raises(KeyboardInterrupt):  # the second one quits at once
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(0.5)
    assert runcontrol.current() is None



def test_stay_awake_holds_once_for_nested_steps_and_releases_at_the_end(monkeypatch):
    from unittest import mock
    helper = mock.Mock()
    start = mock.Mock(return_value=helper)
    monkeypatch.setattr(runcontrol, "_start_awake_helper", start)
    monkeypatch.setattr(runcontrol.os, "name", "posix")
    with runcontrol.stay_awake():
        with runcontrol.stay_awake():  # a step inside a step: still one hold
            assert start.call_count == 1
        helper.terminate.assert_not_called()
    helper.terminate.assert_called_once()
    assert runcontrol._awake_helper is None


def test_stay_awake_changes_nothing_where_no_tool_exists(monkeypatch):
    monkeypatch.setattr(runcontrol, "_start_awake_helper", lambda why: None)
    monkeypatch.setattr(runcontrol.os, "name", "posix")
    with runcontrol.stay_awake():
        pass
    assert runcontrol._awake_helper is None
