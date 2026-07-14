"""
stencil_lib.py — Generic parametric stencil generator.

One engine, many curve families. A Stencil is a print-accurate transparent
canvas (sized in real-world cm at a given DPI); curves are added by name
from a small registry of parametric formulas, or by passing your own
x(t), y(t) functions directly. New stencil types = new formula, not new
script.

Built-in curve families:
  - "ellipse"            the curve traced by a Trammel of Archimedes
  - "archimedean_spiral" r = a + b*theta   (evenly spaced coils)
  - "golden_spiral"      true logarithmic spiral with golden-ratio growth
  - "golden_grid_spiral" the square-subdivision construction (quarter-arcs)
  - "spirograph"         hypotrochoid (R, r, d)
  - "rose"               rose curve r = cos(k*theta)
  - "polygon"            regular n-gon

Usage:
    s = Stencil(width_cm=8.7, height_cm=5.2, dpi=300)
    s.add_curve("ellipse", a_cm=4, b_cm=2.5)
    s.add_curve("archimedean_spiral", turns=4, spacing_cm=0.4)
    s.save("out.png")
"""

import math
from PIL import Image, ImageDraw


PHI = (1 + math.sqrt(5)) / 2


def _linspace(a, b, n):
    if n <= 1:
        return [a]
    step = (b - a) / (n - 1)
    return [a + i * step for i in range(n)]


# ---------------------------------------------------------------------------
# Curve registry: each factory takes canvas half-extents (rx_cm, ry_cm) plus
# kwargs, and returns (x_func, y_func, t0, t1, closed) where x_func/y_func
# are in cm, centered on (0, 0).
# ---------------------------------------------------------------------------

def _ellipse(rx_cm, ry_cm, a_cm=None, b_cm=None, rotation_deg=0, **_):
    a = a_cm if a_cm is not None else rx_cm * 0.9
    b = b_cm if b_cm is not None else ry_cm * 0.9
    rot = math.radians(rotation_deg)

    def x(t):
        return a * math.cos(t) * math.cos(rot) - b * math.sin(t) * math.sin(rot)

    def y(t):
        return a * math.cos(t) * math.sin(rot) + b * math.sin(t) * math.cos(rot)

    return x, y, 0, 2 * math.pi, True


def _archimedean_spiral(rx_cm, ry_cm, turns=3, spacing_cm=0.5, start_radius_cm=0.0, **_):
    b = spacing_cm / (2 * math.pi)

    def r(t):
        return start_radius_cm + b * t

    x = lambda t: r(t) * math.cos(t)
    y = lambda t: r(t) * math.sin(t)
    return x, y, 0, 2 * math.pi * turns, False


def _golden_spiral(rx_cm, ry_cm, turns=2, start_radius_cm=0.2, **_):
    growth = math.log(PHI) / (math.pi / 2)

    def r(t):
        return start_radius_cm * math.exp(growth * t)

    x = lambda t: r(t) * math.cos(t)
    y = lambda t: r(t) * math.sin(t)
    return x, y, 0, 2 * math.pi * turns, False


def _spirograph(rx_cm, ry_cm, R_cm=4, r_cm=1.5, d_cm=2, turns=None, **_):
    R, r, d = R_cm, r_cm, d_cm
    from math import gcd
    if turns is None:
        # loop count until the pattern closes (approx via ratio of R,r)
        g = gcd(int(round(R * 100)), int(round(r * 100)))
        turns = max(1, int(round(r * 100 / g)))

    def x(t):
        return (R - r) * math.cos(t) + d * math.cos((R - r) / r * t)

    def y(t):
        return (R - r) * math.sin(t) - d * math.sin((R - r) / r * t)

    return x, y, 0, 2 * math.pi * turns, True


def _rose(rx_cm, ry_cm, k=5, scale_cm=None, **_):
    scale = scale_cm if scale_cm is not None else min(rx_cm, ry_cm) * 0.9

    def r(t):
        return scale * math.cos(k * t)

    x = lambda t: r(t) * math.cos(t)
    y = lambda t: r(t) * math.sin(t)
    period = 2 * math.pi if k % 2 else math.pi
    return x, y, 0, 2 * period, True


def _polygon(rx_cm, ry_cm, sides=6, radius_cm=None, rotation_deg=-90, **_):
    radius = radius_cm if radius_cm is not None else min(rx_cm, ry_cm) * 0.9
    rot = math.radians(rotation_deg)

    def x(t):
        return radius * math.cos(t + rot)

    def y(t):
        return radius * math.sin(t + rot)

    # sampled at exact vertex angles only; add_curve will still subdivide,
    # which is harmless for straight edges (points just lie on the lines)
    return x, y, 0, 2 * math.pi, True, sides  # extra: vertex count hint


_REGISTRY = {
    "ellipse": _ellipse,
    "archimedean_spiral": _archimedean_spiral,
    "golden_spiral": _golden_spiral,
    "spirograph": _spirograph,
    "rose": _rose,
    "polygon": _polygon,
}


class Stencil:
    def __init__(self, width_cm, height_cm=None, dpi=300, margin_cm=0.0):
        self.width_cm = width_cm
        self.height_cm = height_cm if height_cm is not None else width_cm / PHI
        self.dpi = dpi
        self.px_per_cm = dpi / 2.54
        self.margin_cm = margin_cm
        self.W = round(self.width_cm * self.px_per_cm)
        self.H = round(self.height_cm * self.px_per_cm)
        self.img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)
        self.cx, self.cy = self.W / 2, self.H / 2

    def _to_px(self, x_cm, y_cm):
        return (self.cx + x_cm * self.px_per_cm, self.cy - y_cm * self.px_per_cm)

    def add_frame(self, stroke=(255, 255, 255, 255), width_px=3):
        self.draw.rectangle([0, 0, self.W - 1, self.H - 1], outline=stroke, width=width_px)

    def add_parametric(self, x_func, y_func, t0, t1, steps=720, closed=False,
                        stroke=(255, 255, 255, 255), width_px=3):
        ts = _linspace(t0, t1, steps)
        pts = [self._to_px(x_func(t), y_func(t)) for t in ts]
        if closed:
            pts.append(pts[0])
        self.draw.line(pts, fill=stroke, width=width_px, joint="curve")

    def add_curve(self, name, steps=720, stroke=(255, 255, 255, 255), width_px=3, **kwargs):
        if name not in _REGISTRY:
            raise ValueError(f"Unknown curve '{name}'. Options: {list(_REGISTRY)}")
        rx_cm = self.width_cm / 2 - self.margin_cm
        ry_cm = self.height_cm / 2 - self.margin_cm
        result = _REGISTRY[name](rx_cm, ry_cm, **kwargs)
        x_func, y_func, t0, t1, closed = result[:5]
        if name == "polygon":
            sides = result[5]
            steps = sides + 1  # straight edges only need vertices
        self.add_parametric(x_func, y_func, t0, t1, steps=steps, closed=closed,
                             stroke=stroke, width_px=width_px)

    def add_golden_grid_spiral(self, stroke=(255, 255, 255, 255), width_px=3,
                                show_grid=True, min_square_px=8):
        """The square-subdivision construction (as in classic diagrams),
        kept separate since it's grid-based rather than a single formula."""
        W, H = self.W, self.H
        x, y, w, h, direction = 0, 0, W, H, 0
        squares = []
        while min(w, h) > min_square_px and len(squares) < 30:
            side = min(w, h)
            if direction == 0:
                squares.append((x, y, side, direction)); x += side; w -= side
            elif direction == 1:
                squares.append((x, y, side, direction)); y += side; h -= side
            elif direction == 2:
                squares.append((x + w - side, y, side, direction)); w -= side
            else:
                squares.append((x, y + h - side, side, direction)); h -= side
            direction = (direction + 1) % 4

        for (sx, sy, side, orientation) in squares:
            if show_grid:
                self.draw.rectangle([sx, sy, sx + side, sy + side],
                                     outline=stroke, width=max(1, width_px - 1))
            if orientation == 0:
                cx, cy, start, end = sx, sy + side, 270, 360
            elif orientation == 1:
                cx, cy, start, end = sx, sy, 0, 90
            elif orientation == 2:
                cx, cy, start, end = sx + side, sy, 90, 180
            else:
                cx, cy, start, end = sx + side, sy + side, 180, 270
            bbox = [cx - side, cy - side, cx + side, cy + side]
            self.draw.arc(bbox, start=start, end=end, fill=stroke, width=width_px)

    def composite_on(self, rgb=(139, 105, 70)):
        bg = Image.new("RGB", self.img.size, rgb)
        bg.paste(self.img, (0, 0), self.img)
        return bg

    def save(self, path):
        self.img.save(path)


if __name__ == "__main__":
    demos = [
        ("ellipse", dict(a_cm=3.8, b_cm=2.2)),
        ("archimedean_spiral", dict(turns=4, spacing_cm=0.35)),
        ("golden_spiral", dict(turns=2)),
        ("spirograph", dict(R_cm=3.5, r_cm=1.3, d_cm=1.8)),
        ("rose", dict(k=5)),
        ("polygon", dict(sides=6)),
    ]
    tile = Image.new("RGB", (900, 600), (30, 30, 30))
    from PIL import ImageOps
    cols, rows = 3, 2
    cw, ch = 300, 300
    for i, (name, kwargs) in enumerate(demos):
        s = Stencil(width_cm=6, height_cm=6, dpi=150, margin_cm=0.3)
        s.add_frame(width_px=2)
        s.add_curve(name, width_px=3, **kwargs)
        thumb = s.composite_on((45, 45, 45)).resize((cw, ch))
        cx, cy = (i % cols) * cw, (i // cols) * ch
        tile.paste(thumb, (cx, cy))
    tile.save("./stencil_contact_sheet.png")
    print("saved contact sheet")
