"""Swept collision helpers."""

import math


def segment_circle_entry(
    x0: float, y0: float, x1: float, y1: float, cx: float, cy: float, r: float
) -> float:
    """Return the fraction t in [0, 1] along segment (x0,y0)->(x1,y1) where it first
    touches the circle (cx, cy, r), or -1.0 if it never does. Starting inside counts
    as t = 0."""
    fx = x0 - cx
    fy = y0 - cy
    c = fx * fx + fy * fy - r * r
    if c <= 0.0:
        return 0.0
    dx = x1 - x0
    dy = y1 - y0
    a = dx * dx + dy * dy
    if a == 0.0:
        return -1.0
    half_b = fx * dx + fy * dy
    if half_b >= 0.0:  # moving away from the circle
        return -1.0
    disc = half_b * half_b - a * c
    if disc < 0.0:
        return -1.0
    t = (-half_b - math.sqrt(disc)) / a
    return t if t <= 1.0 else -1.0


def segment_capsule_entry(
    x0: float, y0: float, x1: float, y1: float,
    ax: float, ay: float, bx: float, by: float, r: float,
) -> float:
    """First t in [0, 1] where the point moving (x0,y0)->(x1,y1) comes within r of
    segment AB (i.e. a circle of radius r touches the segment), or -1.0."""
    ux = bx - ax
    uy = by - ay
    length = math.hypot(ux, uy)
    if length == 0.0:
        return segment_circle_entry(x0, y0, x1, y1, ax, ay, r)
    ux /= length
    uy /= length
    nx, ny = -uy, ux
    # Already touching?
    along0 = (x0 - ax) * ux + (y0 - ay) * uy
    side0 = (x0 - ax) * nx + (y0 - ay) * ny
    if 0.0 <= along0 <= length and abs(side0) <= r:
        return 0.0
    best = 2.0
    # The flat sides of the capsule.
    dn = (x1 - x0) * nx + (y1 - y0) * ny
    if dn != 0.0 and abs(side0) > r:
        target = r if side0 > 0.0 else -r
        t = (target - side0) / dn
        if 0.0 <= t <= 1.0:
            along = along0 + t * ((x1 - x0) * ux + (y1 - y0) * uy)
            if 0.0 <= along <= length:
                best = t
    # The rounded ends.
    for cx, cy in ((ax, ay), (bx, by)):
        t = segment_circle_entry(x0, y0, x1, y1, cx, cy, r)
        if 0.0 <= t < best:
            best = t
    return best if best <= 1.0 else -1.0


def segment_box_exit(x0: float, y0: float, x1: float, y1: float, w: float, h: float) -> float:
    """First t in [0, 1] where the point moving (x0,y0)->(x1,y1) leaves the box
    [0, w] x [0, h], or -1.0 if it ends inside. Starting outside counts as t = 0."""
    if x0 < 0.0 or x0 > w or y0 < 0.0 or y0 > h:
        return 0.0
    best = 2.0
    dx = x1 - x0
    dy = y1 - y0
    if x1 < 0.0:
        best = min(best, -x0 / dx)
    elif x1 > w:
        best = min(best, (w - x0) / dx)
    if y1 < 0.0:
        best = min(best, -y0 / dy)
    elif y1 > h:
        best = min(best, (h - y0) / dy)
    return best if best <= 1.0 else -1.0
