# SelectingTopMaterial/palette.py
"""The colours of the classes, in the workbook and in the report.

The classes are an order — best to worst — so they are steps of one hue, the best class the most
visible: darkest on a light page, lightest on a dark one. The rejected class is not a step of
that order, it is out of it: grey. A colour never stands alone; the name of the class is always
written beside it."""

from __future__ import annotations

_BLUE = {200: "#9ec5f4", 250: "#86b6ef", 300: "#6da7ec", 350: "#5598e7", 400: "#3987e5", 450: "#2a78d6",
         500: "#256abf", 550: "#1c5cab", 600: "#184f95"}
# Best class first. Step 250 is the lightest that still shows on a light page, 600 the darkest
# that still shows on a dark one.
_ON_LIGHT = (600, 550, 500, 450, 400, 350, 300, 250)
_ON_DARK = (200, 250, 300, 350, 400, 450, 500, 550, 600)
REJECTED = "#898781"


def class_colours(accepted: int, dark: bool = False) -> list[str]:
    """One colour for each accepted class, best first, spread over the steps of the hue."""
    steps = _ON_DARK if dark else _ON_LIGHT
    if accepted <= 1:
        return [_BLUE[steps[len(steps) // 2]]] * accepted
    return [_BLUE[steps[int(index * (len(steps) - 1) / (accepted - 1))]] for index in range(accepted)]


def ink_on(colour: str) -> str:
    """Black or white, whichever reads on the colour."""
    red, green, blue = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (red, green, blue)]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#0b0b0b" if luminance > 0.24 else "#ffffff"
