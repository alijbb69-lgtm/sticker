"""بخش‌بندی نوشته‌ها در تصویر PNG: پیکسل‌های «نوشته» پیدا، به مؤلفه و سپس به خوشه (کلمه/عدد) گروه می‌شوند."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter


@dataclass
class Cluster:
    bbox: tuple[int, int, int, int]            # x0, y0, x1, y1 (x1,y1 انحصاری)
    mask: np.ndarray                           # bool، اندازه‌ی bbox
    n_comp: int
    color: tuple[int, int, int] = (0, 0, 0)
    comps: list = field(default_factory=list)


def _label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """برچسب‌گذاری مؤلفه‌های هم‌بند (۸ همسایگی) با پیمایش عمقی؛ بدون وابستگی به scipy."""
    h, w = mask.shape
    lab = np.zeros((h, w), dtype=np.int32)
    n = 0
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if lab[y0, x0]:
            continue
        n += 1
        lab[y0, x0] = n
        stack = [(y0, x0)]
        while stack:
            y, x = stack.pop()
            for dy in (-1, 0, 1):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < w and mask[yy, xx] and not lab[yy, xx]:
                        lab[yy, xx] = n
                        stack.append((yy, xx))
    return lab, n


def background_distance(img: Image.Image) -> np.ndarray:
    """فاصله‌ی رنگ هر پیکسل با پس‌زمینه‌ی تخمینی (میانه‌ی بزرگ روی نسخه‌ی کوچک‌شده؛ برای خطوط ضخیم هم کار می‌کند)."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    small = rgb.resize((max(1, w // 4), max(1, h // 4)), Image.BILINEAR)
    bg = small.filter(ImageFilter.MedianFilter(31)).resize((w, h), Image.BILINEAR)
    a = np.asarray(rgb, dtype=np.float32)
    b = np.asarray(bg, dtype=np.float32)
    return np.abs(a - b).max(axis=2)


def find_clusters(img: Image.Image, thr: float = 40.0, max_comp_h: int = 150, max_comp_w: int = 260) -> list[Cluster]:
    rgba = img.convert("RGBA")
    alpha = np.asarray(rgba)[..., 3]
    d = background_distance(rgba)
    mask = (d > thr) & (alpha > 128)
    lab, n = _label(mask)
    rgb = np.asarray(rgba.convert("RGB"))
    comps = []
    if n:
        objs = _bboxes(lab, n)
        for i, (x0, y0, x1, y1, area) in objs.items():
            w, h = x1 - x0, y1 - y0
            if area < 8 or h > max_comp_h or w > max_comp_w or h < 4:
                continue
            fill = area / float(w * h)
            if fill < 0.08:               # خط باریکِ بلند = لبه‌ی شکل، نه حرف
                continue
            px = rgb[y0:y1, x0:x1][lab[y0:y1, x0:x1] == i].astype(np.float32)
            if px.std(axis=0).max() > 55:  # رنگ ناهمگن (شکل/گرادیان/لوگو)، نه نوشته‌ی تک‌رنگ
                continue
            comps.append((x0, y0, x1, y1, i, np.median(px, axis=0)))
    # گروه‌بندی مؤلفه‌ها به خوشه
    parent = list(range(len(comps)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(len(comps)):
        ax0, ay0, ax1, ay1, _, acol = comps[i]
        for j in range(i + 1, len(comps)):
            bx0, by0, bx1, by1, _, bcol = comps[j]
            if np.abs(acol - bcol).max() > 70:      # رنگ متفاوت = نوشته‌ی دیگر/شکل
                continue
            vo = min(ay1, by1) - max(ay0, by0)
            hmin = min(ay1 - ay0, by1 - by0)
            if vo < 0.35 * max(1, hmin):
                continue
            gap = max(bx0 - ax1, ax0 - bx1)
            hmax = max(ay1 - ay0, by1 - by0)
            if gap <= 0.55 * hmax and 0.45 < (ay1 - ay0) / max(1, by1 - by0) < 2.2:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(comps)):
        groups.setdefault(find(i), []).append(i)
    # نقطه‌ها و علامت‌های بالا/پایین حروف (ب، ج، آ …) را به خوشه‌ی زیر/بالایشان بچسبان
    def gbox(idxs):
        return (min(comps[i][0] for i in idxs), min(comps[i][1] for i in idxs),
                max(comps[i][2] for i in idxs), max(comps[i][3] for i in idxs))
    for key in list(groups):
        idxs = groups.get(key)
        if idxs is None or len(idxs) != 1:
            continue
        x0, y0, x1, y1, _, col = comps[idxs[0]]
        if (y1 - y0) > 22:
            continue
        for k2, other in groups.items():
            if k2 == key:
                continue
            ox0, oy0, ox1, oy1 = gbox(other)
            oh = oy1 - oy0
            if (y1 - y0) > 0.6 * oh:
                continue
            ocol = comps[other[0]][5]
            if np.abs(col - ocol).max() > 70:
                continue
            xo = min(x1, ox1) - max(x0, ox0)
            vgap = max(y0 - oy1, oy0 - y1)
            if xo > 0 and vgap <= 0.8 * oh:
                other.append(idxs[0])
                del groups[key]
                break
    out: list[Cluster] = []
    for idxs in groups.values():
        x0 = min(comps[i][0] for i in idxs)
        y0 = min(comps[i][1] for i in idxs)
        x1 = max(comps[i][2] for i in idxs)
        y1 = max(comps[i][3] for i in idxs)
        m = np.zeros((y1 - y0, x1 - x0), dtype=bool)
        for i in idxs:
            m |= (lab[y0:y1, x0:x1] == comps[i][4])
        if m.sum() < 30:
            continue
        col = tuple(int(v) for v in np.median(rgb[y0:y1, x0:x1][m], axis=0))
        out.append(Cluster((x0, y0, x1, y1), m, len(idxs), col))
    return out


def _bboxes(lab: np.ndarray, n: int) -> dict:
    res = {}
    ys, xs = np.nonzero(lab)
    labs = lab[ys, xs]
    order = np.argsort(labs, kind="stable")
    labs, ys, xs = labs[order], ys[order], xs[order]
    starts = np.searchsorted(labs, np.arange(1, n + 1), side="left")
    ends = np.searchsorted(labs, np.arange(1, n + 1), side="right")
    for i in range(n):
        s, e = starts[i], ends[i]
        if e > s:
            yy, xx = ys[s:e], xs[s:e]
            res[i + 1] = (int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1, e - s)
    return res
