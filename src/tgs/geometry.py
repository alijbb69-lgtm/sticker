"""هندسه‌ی مسیرهای Lottie: نمونه‌برداری از بزیه، جعبه‌ی محیطی، تبدیل."""
from __future__ import annotations

from .props import Mat, mat_apply, mat_apply_vec


def flatten_path(path: dict, steps: int = 8, matrix: Mat | None = None) -> list[tuple[float, float]]:
    """نقاط چندضلعی تقریبی یک مسیر Lottie ({i,o,v,c})."""
    v, i_t, o_t = path["v"], path["i"], path["o"]
    n = len(v)
    pts: list[tuple[float, float]] = []
    closed = path.get("c", True)
    last = n if closed else n - 1
    for k in range(last):
        p0 = v[k]
        p3 = v[(k + 1) % n]
        c1 = (p0[0] + o_t[k][0], p0[1] + o_t[k][1])
        c2 = (p3[0] + i_t[(k + 1) % n][0], p3[1] + i_t[(k + 1) % n][1])
        straight = o_t[k] == [0, 0] or tuple(o_t[k]) == (0, 0)
        straight = straight and (tuple(i_t[(k + 1) % n]) == (0, 0))
        m = 1 if straight else steps
        for s in range(m):
            u = s / m
            a, b, cc, d = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3
            pts.append((a * p0[0] + b * c1[0] + cc * c2[0] + d * p3[0],
                        a * p0[1] + b * c1[1] + cc * c2[1] + d * p3[1]))
    if not closed and n:
        pts.append((v[-1][0], v[-1][1]))
    if matrix is not None:
        pts = [mat_apply(matrix, x, y) for x, y in pts]
    return pts


def path_bbox(path: dict, matrix: Mat | None = None) -> tuple[float, float, float, float] | None:
    pts = flatten_path(path, 8, matrix)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def union_bbox(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def transform_path(path: dict, m: Mat) -> dict:
    """ماتریس را روی رأس‌ها (کامل) و تانژانت‌ها (فقط بخش خطی) اعمال می‌کند."""
    return {
        "v": [list(mat_apply(m, x, y)) for x, y in path["v"]],
        "i": [list(mat_apply_vec(m, x, y)) for x, y in path["i"]],
        "o": [list(mat_apply_vec(m, x, y)) for x, y in path["o"]],
        "c": path.get("c", True),
    }
