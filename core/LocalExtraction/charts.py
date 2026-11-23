# LocalExtraction/charts.py
"""Draws the charts of LocalExtraction/stats.py with matplotlib, and saves them.

    figure(chart, dark=False)          a matplotlib Figure (no pyplot: safe on a working thread)
    save(charts, source)               ~/MoukhlijMatExtract/Statistics/PNG/<source>_<chart>_<date>.png (300 dpi)
                                       ~/MoukhlijMatExtract/Statistics/SVG/<source>_<chart>_<date>.svg

The look, the same in every window: the data in one quiet grey, ONE accent on what the title is about, the numbers on
the bars (no ruler behind them), the finding in the title, where the numbers come from in a small line under the
chart. On screen it follows the light or dark appearance; a saved file is always light (journals print on white)."""

from __future__ import annotations

import math
import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .stats import Chart

DPI = 300
STATISTICS = "Statistics"
FORMATS = (("PNG", ".png"), ("SVG", ".svg"))
THEMES: Dict[str, Dict[str, str]] = {
    "light": {"bg": "#ffffff", "ink": "#1f2328", "muted": "#6b7280", "grey": "#b8bec7", "accent": "#1f4e79",
              "line": "#d5dbe3"},
    "dark": {"bg": "#2a2e35", "ink": "#eef0f2", "muted": "#9ba3ad", "grey": "#5d646e", "accent": "#7fa8e0",
             "line": "#3b414a"},
}
WIDTH = 7.6  # inches: about the width of a page's text column at 300 dpi


def _figure_class():
    from matplotlib.figure import Figure  # imported when first drawn: a window that never draws does not pay for it
    return Figure


def _count(value: float, percent: bool = False) -> str:
    if percent:
        return f"{100 * value:.0f} %"
    return f"{value:,.0f}" if float(value).is_integer() or abs(value) >= 100 else f"{value:,.2f}"


def _height(chart: Chart) -> float:
    if chart.kind in ("barh", "funnel"):
        return max(3.0, 0.34 * len(chart.labels) + 1.6)
    if chart.kind == "grouped":
        return max(3.2, 0.5 * len(chart.labels) + 1.8)
    return 4.0


def figure(chart: Chart, dark: bool = False, width: float = WIDTH):
    """The chart drawn, as a Figure (light or dark)."""
    t = THEMES["dark" if dark else "light"]
    fig = _figure_class()(figsize=(width, _height(chart)), facecolor=t["bg"])
    ax = fig.add_axes((0.08, 0.16, 0.88, 0.66))
    ax.set_facecolor(t["bg"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["line"])
    ax.tick_params(colors=t["muted"], labelsize=8.5, length=0)
    colours = [t["accent"] if i == chart.accent else t["grey"] for i in range(len(chart.labels))]

    if not (chart.values or chart.series):
        ax.set_axis_off()
        ax.text(0.5, 0.5, "Nothing to draw yet", ha="center", va="center", color=t["muted"], transform=ax.transAxes)
    elif chart.kind == "bar":
        _bars(ax, chart, colours, t)
    elif chart.kind in ("barh", "funnel"):
        _bars_across(ax, chart, colours, t)
    elif chart.kind == "hist":
        _histogram(ax, chart, t)
    elif chart.kind == "grouped":
        _grouped(ax, chart, t)
    elif chart.kind == "line":
        ax.plot(range(len(chart.values)), chart.values, color=t["accent"], linewidth=2)
        _x_labels(ax, chart.labels)
        ax.set_ylabel(chart.unit, color=t["muted"], fontsize=8.5)

    title = textwrap.fill(chart.title, 72)  # bold 11.5 pt: about 72 characters across the figure
    fig.text(0.02, 0.97, title, ha="left", va="top", fontsize=11.5, fontweight="bold", color=t["ink"])
    if chart.note:
        fig.text(0.02, 0.02, textwrap.fill(chart.note, 130), ha="left", va="bottom", fontsize=7.5, color=t["muted"])
    _fit(fig, ax, title, chart)
    return fig


def _fit(fig, ax, title: str, chart: Chart) -> None:
    """Room for the title above and the note below, in inches whatever the height."""
    height = fig.get_figheight()
    top = 1 - (0.32 + 0.2 * title.count("\n") + (0.22 if chart.marks else 0)) / height - 0.04
    bottom = (0.62 + (0.12 if chart.note and len(chart.note) > 130 else 0)) / height
    left = 0.30 if chart.kind in ("barh", "funnel", "grouped") else 0.08
    ax.set_position((left, bottom, 0.95 - left, max(top - bottom, 0.2)))


def _x_labels(ax, labels: Sequence[str]) -> None:
    every = max(1, math.ceil(len(labels) / 18))  # at most ~18 labels under the axis (a run of years)
    ax.set_xticks(range(0, len(labels), every))
    ax.set_xticklabels([labels[i] for i in range(0, len(labels), every)],
                       rotation=0 if max((len(l) for l in labels), default=0) <= 12 else 20, ha="center")


def _bars(ax, chart: Chart, colours: List[str], t: Dict[str, str]) -> None:
    xs = range(len(chart.values))
    ax.bar(xs, chart.values, width=0.62, color=colours, edgecolor=t["bg"], linewidth=0.8)
    _x_labels(ax, chart.labels)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    top = max(chart.values) or 1
    ax.set_ylim(0, top * 1.16)
    if len(chart.values) <= 24:
        for x, v in zip(xs, chart.values):
            ax.text(x, v + top * 0.015, _count(v, chart.percent), ha="center", va="bottom", fontsize=8.5,
                    color=t["ink"])
    elif chart.unit:  # too many bars to number: a scale says how tall they are
        ax.set_yticks(ax.get_yticks())
        ax.spines["left"].set_visible(True)
        ax.set_ylabel(chart.unit, color=t["muted"], fontsize=8.5)


def _bars_across(ax, chart: Chart, colours: List[str], t: Dict[str, str]) -> None:
    """Horizontal bars, the first label on top; a funnel adds the share each stage keeps of the one before."""
    n = len(chart.values)
    ys = list(range(n))[::-1]
    ax.barh(ys, chart.values, height=0.62, color=colours, edgecolor=t["bg"], linewidth=0.8)
    ax.set_yticks(ys)
    ax.set_yticklabels([textwrap.shorten(l, 40, placeholder="…") for l in chart.labels], fontsize=8.5, color=t["ink"])
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    top = max(chart.values) or 1
    ax.set_xlim(0, top * (1.42 if chart.kind == "funnel" else 1.18))
    for i, (y, v) in enumerate(zip(ys, chart.values)):
        text = _count(v, chart.percent)
        if chart.kind == "funnel" and i:
            before = chart.values[i - 1]
            text += f"   {100 * v / before:.1f} % of the stage above" if before else ""
        ax.text(v + top * 0.012, y, text, va="center", ha="left", fontsize=8.5, color=t["ink"])
    if chart.unit:
        ax.set_xlabel(chart.unit, color=t["muted"], fontsize=8.5)


def _histogram(ax, chart: Chart, t: Dict[str, str]) -> None:
    samples = [math.log10(v) for v in chart.values if v > 0] if chart.log10 else list(chart.values)
    if not samples:
        return
    width = chart.bin_width or (max(samples) - min(samples)) / 20 or 1
    low, high = math.floor(min(samples) / width) * width, math.ceil(max(samples) / width) * width
    edges = [low + i * width for i in range(int(round((high - low) / width)) + 1)] or [low, low + width]
    if len(edges) < 2:
        edges = [low, low + width]
    ax.hist(samples, bins=edges, color=t["grey"], edgecolor=t["bg"], linewidth=0.8)
    ax.set_xlabel(chart.unit, color=t["muted"], fontsize=8.5)
    ax.set_ylabel("values", color=t["muted"], fontsize=8.5)
    shown = [(value, label) for value, label in chart.marks if low <= value <= high]
    for n, (value, label) in enumerate(shown):
        ax.axvline(value, color=t["muted"], linewidth=0.9, linestyle=(0, (4, 3)))
        # Above the plot, never over the bars or a line; close lines take turns at two heights.
        ax.text(value, 1.02 + 0.07 * (n % 2), label, transform=ax.get_xaxis_transform(), ha="center", va="bottom",
                fontsize=7.5, color=t["muted"], clip_on=False)


def _grouped(ax, chart: Chart, t: Dict[str, str]) -> None:
    """Several series per label, side by side, across (the first label on top)."""
    names = list(chart.series)
    n, k = len(chart.labels), max(len(names), 1)
    band = 0.8 / k
    shades = [t["grey"], t["accent"]] if k == 2 else [t["accent"]] * k
    alphas = [1.0, 1.0] if k == 2 else [0.35 + 0.65 * i / max(k - 1, 1) for i in range(k)]
    top = max((v for vs in chart.series.values() for v in vs), default=1) or 1
    for j, name in enumerate(names):
        ys = [(n - 1 - i) + 0.4 - band * (j + 0.5) for i in range(n)]
        values = chart.series[name]
        ax.barh(ys, values, height=band * 0.92, color=shades[j], alpha=alphas[j], label=name, edgecolor=t["bg"])
        for y, v in zip(ys, values):
            ax.text(v + top * 0.01, y, _count(v, chart.percent), va="center", fontsize=7.5, color=t["ink"])
    ax.set_yticks(range(n))
    ax.set_yticklabels([textwrap.shorten(l, 40, placeholder="…") for l in chart.labels[::-1]], fontsize=8.5,
                       color=t["ink"])
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.set_xlim(0, top * 1.2)
    legend = ax.legend(loc="lower right", fontsize=8, frameon=False)
    for text in legend.get_texts():
        text.set_color(t["ink"])


# ---------------------------------------------------------------------------------------------------- saving
def slug(text: str) -> str:
    """A part of a file name: "Web scraping · garnet_nasicon" → "web-scraping-garnet_nasicon"."""
    text = re.sub(r"[^a-z0-9_-]+", "-", str(text).lower()).strip("-")
    return text or "statistics"


def folder(home: Optional[Path] = None) -> Path:
    """~/MoukhlijMatExtract/Statistics (its PNG/ and SVG/ folders hold the saved charts)."""
    if home is None:
        from .about import PROJECT_HOME
        home = PROJECT_HOME
    return Path(home) / STATISTICS


def save(charts: Sequence[Chart], source: str, home: Optional[Path] = None,
         when: Optional[datetime] = None) -> List[Path]:
    """Every chart as a 300 dpi PNG in Statistics/PNG/ and as an SVG in Statistics/SVG/, named
    <source>_<chart>_<date and time>; returns the files written. Light, whatever the screen's appearance."""
    stamp = (when or datetime.now()).strftime("%Y-%m-%d_%H%M")
    root = folder(home)
    written: List[Path] = []
    for kind, suffix in FORMATS:
        (root / kind).mkdir(parents=True, exist_ok=True)
    for chart in charts:
        fig = figure(chart, dark=False)
        try:
            for kind, suffix in FORMATS:
                path = root / kind / f"{slug(source)}_{slug(chart.key)}_{stamp}{suffix}"
                fig.savefig(path, dpi=DPI if suffix == ".png" else None, facecolor=fig.get_facecolor())
                written.append(path)
        finally:
            fig.clear()
    return written
