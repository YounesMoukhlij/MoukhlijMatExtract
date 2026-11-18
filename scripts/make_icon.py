# scripts/make_icon.py
"""Draws the program's icon, LocalExtraction/gui/assets/mme_icon.png (512 × 512): the emblem of the windows' header
(design.emblem — a unit cell in perspective, its atoms on the corners and a garnet one in the middle) on the navy of
the header band, in a rounded square with the margins of a macOS icon.

    python scripts/make_icon.py"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE, SCALE = 512, 4                 # drawn 4 times larger, then reduced: smooth edges
OUT = Path(__file__).resolve().parents[1] / "LocalExtraction" / "gui" / "assets" / "mme_icon.png"
NAVY_TOP, NAVY_BOTTOM = (0x1b, 0x3f, 0x72), (0x0e, 0x22, 0x3f)   # theme.palette: band (light → dark)
LINE, WHITE, GARNET = (0x9f, 0xb3, 0xcf), (255, 255, 255), (0x8c, 0x1d, 0x40)


def main() -> Path:
    big = SIZE * SCALE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    # The rounded square: 80 % of the canvas, as macOS draws an application's icon.
    margin, radius = int(big * 0.10), int(big * 0.18)
    box = (margin, margin, big - margin, big - margin)
    gradient = Image.new("RGBA", (big, big))
    pixels = ImageDraw.Draw(gradient)
    for y in range(big):
        t = min(max((y - margin) / (big - 2 * margin), 0.0), 1.0)
        pixels.line([(0, y), (big, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOTTOM)) + (255,))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    image.paste(gradient, (0, 0), mask)
    draw = ImageDraw.Draw(image)
    # A thin garnet rule near the bottom, as under the header band.
    rule = int(big * 0.018)
    draw.rounded_rectangle((margin + radius, big - margin - int(big * 0.115), big - margin - radius,
                            big - margin - int(big * 0.115) + rule), radius=rule // 2, fill=GARNET + (255,))

    # The unit cell of design.emblem (a 42-unit square), centred and enlarged.
    unit = big * 0.0125
    shift_x, shift_y = big * 0.5 - 21 * unit, big * 0.47 - 20 * unit
    point = lambda x, y: (shift_x + x * unit, shift_y + y * unit)  # noqa: E731
    front = [point(*p) for p in ((6, 14), (26, 14), (26, 34), (6, 34))]
    back = [point(*p) for p in ((16, 6), (36, 6), (36, 26), (16, 26))]
    thin, thick = int(unit * 0.9), int(unit * 1.5)
    for a, b in zip(back, back[1:] + back[:1]):
        draw.line([a, b], fill=LINE + (255,), width=thin)
    for a, b in zip(front, back):
        draw.line([a, b], fill=LINE + (255,), width=thin)
    for a, b in zip(front, front[1:] + front[:1]):
        draw.line([a, b], fill=WHITE + (255,), width=thick)
    atom = unit * 2.6
    for x, y in back + front:
        draw.ellipse((x - atom, y - atom, x + atom, y + atom), fill=LINE + (255,))
    cx, cy = point(21, 20)
    centre, ring = unit * 4.2, unit * 0.9
    draw.ellipse((cx - centre - ring, cy - centre - ring, cx + centre + ring, cy + centre + ring), fill=WHITE + (255,))
    draw.ellipse((cx - centre, cy - centre, cx + centre, cy + centre), fill=GARNET + (255,))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.resize((SIZE, SIZE), Image.LANCZOS).save(OUT, optimize=True)
    return OUT


if __name__ == "__main__":
    print(f"Wrote {main()}")
