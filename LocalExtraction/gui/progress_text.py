# LocalExtraction/gui/progress_text.py
"""The words of a progress line, the same in every window: “1,204 of 2,128”, and the time left once it can be
estimated (“about 6 min left”)."""

from __future__ import annotations

import time
from typing import Optional


def duration(seconds: float) -> str:
    """A time as a person says it: 45 s · 26 min · 1 h 20 min · 14 h · 2 days 3 h · 9 days. Many minutes are said in
    hours, many hours in days."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} s" if seconds < 5 else f"{seconds // 5 * 5} s"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 10:
        return f"{hours} h" if not rest else f"{hours} h {rest} min"
    hours = round(minutes / 60)
    if hours < 24:
        return f"{hours} h"
    days, rest = divmod(hours, 24)
    if days < 7:
        return f"{days} day{'s' if days > 1 else ''}" + (f" {rest} h" if rest else "")
    return f"{round(hours / 24)} days"


def time_left(started: float, done: int, total: int, since: int = 0, now: Optional[float] = None) -> str:
    """“ · about 6 min left”, from the pace since `started` (when `since` items were done); "" until a few items
    and seconds give a pace worth saying, and at the end."""
    now = time.time() if now is None else now
    worked, elapsed = done - since, now - started
    if worked < 2 or elapsed < 4 or done >= total:
        return ""
    return f" · about {duration(elapsed / worked * (total - done))} left"


class Pace:
    """The pace of one phase of a step: `text(phase, done, total)` starts a new clock when the phase changes."""

    def __init__(self) -> None:
        self.phase: Optional[str] = None
        self.started = 0.0
        self.since = 0

    def left(self, phase: str, done: int, total: int, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        if phase != self.phase or done < self.since:
            self.phase, self.started, self.since = phase, now, max(done - 1, 0)
        return time_left(self.started, done, total, self.since, now)
